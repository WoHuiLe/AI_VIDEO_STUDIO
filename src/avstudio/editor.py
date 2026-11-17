"""Project-local editing commands with bounded persistent undo and conflict checks."""
import copy
from .storage import StudioError, load_project, read_json, write_json, atomic_text
from .project import require_valid, export_storyboard
from .production import digest

MANIFESTS = ["project.json", "planning/director.json", "planning/shot_assets.json", "planning/submission.json", "planning/storyboard.csv", "planning/prompts.md", "planning/style.md"]
META = ["approvals", "status", "current_stage", "review_stage", "needs_revision", "error", "plan_revision"]


def content_revision(snapshot):
    content=copy.deepcopy(snapshot)
    content.pop("meta",None)
    for shot in content["shots"]:
        shot.pop("review_status",None)
    return digest(content)


class Editor:
    def __init__(self, production):self.p=production

    def snapshot(self, root):
        data=load_project(root);meta=self.p.meta(root)
        path=root/"planning/director.json"
        return {"plan":read_json(path) if path.exists() else None,"mapping":self.p.mapping(root),
                "shots":data["shots"], "settings": {k:data.get(k) for k in ["width","height","fps","narration_sha256"]},
                "meta":{k:meta.get(k) for k in META}}

    def history(self, root):
        path=root/"work/editor.json"
        history=read_json(path) if path.exists() else {"undo":[],"redo":[],"expected":None}
        if history["expected"]!=content_revision(self.snapshot(root)):
            return {"undo":[],"redo":[],"expected":content_revision(self.snapshot(root))}
        return history

    def view(self, root):
        history=self.history(root)
        return {"revision":content_revision(self.snapshot(root)),"can_undo":bool(history["undo"]),
                "can_redo":bool(history["redo"]),"undo_label":history["undo"][-1]["label"] if history["undo"] else None}

    def record(self, root, before, history, label):
        history["undo"].append({"state":before,"label":label})
        history["undo"]=history["undo"][-30:];history["redo"]=[]
        history["expected"]=content_revision(self.snapshot(root))
        write_json(root/"work/editor.json",history)

    def comparison(self, root, shot_id, progress):
        import math
        from PIL import Image, ImageOps
        from .storage import local
        from .render import frame
        history=self.history(root)
        if not history["undo"] or not math.isfinite(progress) or not 0<=progress<=1:
            raise StudioError("没有可比较的上一版本")
        snapshot=history["undo"][-1]["state"]
        shot=next((s for s in snapshot["shots"] if s["shot_id"]==shot_id),None)
        if not shot:
            raise StudioError("上一版本尚无该镜头的画面")
        data=load_project(root)
        from .render import geometry
        size=geometry(data,True)
        if shot.get("scene"):
            from .scenes import raster
            return raster(shot["scene"],progress,size,shot.get("motion","static"))
        layers=[]
        for spec in shot["layers"]:
            with Image.open(local(root,data["assets"][spec["asset_id"]]["path"])) as source:
                image=ImageOps.exif_transpose(source).convert("RGBA")
                ratio=size[0]/size[1]
                master=(round(image.height*ratio),image.height) if image.width/image.height>ratio else (image.width,round(image.width/ratio))
                layers.append(ImageOps.fit(image,master))
        return frame(layers,shot["layers"],size,progress)

    def restore(self, root, snapshot):
        data=load_project(root);data["shots"]=snapshot["shots"]
        write_json(root/"project.json",data)
        write_json(root/"planning/director.json",snapshot["plan"])
        write_json(root/"planning/shot_assets.json",snapshot["mapping"])
        self.p.update(root,**snapshot["meta"])
        require_valid(root);export_storyboard(root)
        from .taskpacks import image_task
        atomic_text(root/"planning/prompts.md",image_task(data,snapshot["plan"]))

    def apply(self, root, fields):
        self.p.idle(root)
        before=self.snapshot(root)
        if fields.get("revision")!=content_revision(before):
            raise StudioError("工程已被其他操作更新，请刷新后重试；本次修改未保存")
        if not before["plan"]:raise StudioError("请先生成或导入分镜")
        history=self.history(root);operation=fields.get("operation","edit")
        backups={name:(root/name).read_text(encoding="utf-8") if (root/name).exists() else None for name in MANIFESTS}
        try:
            if operation in {"undo","redo"}:
                source=history[operation];target=history["redo" if operation=="undo" else "undo"]
                if not source:raise StudioError("没有可以撤销或重做的编辑；外部导入后历史会重新开始")
                entry=source.pop();target.append({"state":before,"label":entry["label"]})
                self.restore(root,entry["state"])
            else:
                import json,math
                patch=json.loads(fields.get("patch","{}"))
                if not isinstance(patch,dict) or set(patch)-{"visual_description","image_prompt","duration_s","motion","scene","order"}:
                    raise StudioError("不支持这些编辑字段")
                plan=copy.deepcopy(before["plan"])
                sid=fields.get("shot_id")
                shot=next((s for s in plan["shots"] if s["shot_id"]==sid),None)
                if shot is None:raise StudioError("找不到选中的镜头")
                if "order" in patch:
                    order=patch.pop("order")
                    if not isinstance(order,list) or len(order)!=len(plan["shots"]) or set(order)!={s["shot_id"] for s in plan["shots"]}:
                        raise StudioError("镜头顺序必须完整且无重复")
                    plan["shots"]=sorted(plan["shots"],key=lambda s:order.index(s["shot_id"]))
                if "scene" in patch and patch["scene"] is not None:
                    from .scenes import validate_scene
                    validate_scene(patch["scene"])
                if "scene" in patch and patch["scene"] is None:
                    shot.pop("scene",None);patch.pop("scene")
                shot.update(patch)
                from .planner import validate_plan
                validate_plan(plan,load_project(root))
                if plan==before["plan"]:
                    return
                old_planned=next(s for s in before["plan"]["shots"] if s["shot_id"]==sid)
                write_json(root/"planning/director.json",plan)
                # A local edit keeps every unrelated shot, binding and source intact.
                self.p.rebuild(root)
                data=load_project(root)
                previous={s["shot_id"]:s for s in before["shots"]}
                for index,current in enumerate(data["shots"]):
                    if current["shot_id"]!=sid and current["shot_id"] in previous:
                        data["shots"][index]=previous[current["shot_id"]]
                    elif "duration_s" in patch and patch["duration_s"]!=old_planned["duration_s"]:
                        current.update(start_s=None,end_s=None,timeline_status="provisional")
                        current.pop("alignment_audio_sha256",None)
                if "order" in json.loads(fields.get("patch","{}")):
                    for current in data["shots"]:
                        current.update(start_s=None,end_s=None,timeline_status="provisional")
                        current.pop("alignment_audio_sha256",None)
                write_json(root/"project.json",data);require_valid(root);export_storyboard(root)
                approvals=copy.deepcopy(before["meta"]["approvals"] or {})
                if approvals.get("storyboard") and not before["meta"].get("needs_revision"):
                    approvals["storyboard"]=digest(plan)
                approvals.pop("artwork",None)
                self.p.update(root,approvals=approvals,status="awaiting_assets" if approvals.get("storyboard") else "review",
                    current_stage="artwork" if approvals.get("storyboard") else "storyboard",error=None,plan_revision=digest(plan))
                from .taskpacks import image_task
                atomic_text(root/"planning/prompts.md",image_task(data,plan))
                if content_revision(self.snapshot(root))!=content_revision(before):
                    history["undo"].append({"state":before,"label":f"编辑 {sid}"});history["undo"]=history["undo"][-30:];history["redo"]=[]
            history["expected"]=content_revision(self.snapshot(root));write_json(root/"work/editor.json",history)
        except Exception:
            for name,content in backups.items():
                if content is None:(root/name).unlink(missing_ok=True)
                else:atomic_text(root/name,content)
            raise
