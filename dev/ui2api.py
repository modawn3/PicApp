"""ComfyUI UI-format workflow -> API-format prompt, using a live /object_info dump."""
import json, sys

WIDGET_TYPES = {"INT", "FLOAT", "STRING", "BOOLEAN", "COMBO"}

def is_widget(spec):
    t = spec[0]
    return isinstance(t, list) or t in WIDGET_TYPES

def convert(ui, info):
    links = {l[0]: l for l in ui["links"]}  # id, from_node, from_slot, to_node, to_slot, type
    out = {}
    for n in ui["nodes"]:
        if n["type"] in ("Note", "MarkdownNote"):
            continue
        spec = info[n["type"]]["input"]
        order = list(spec.get("required", {}).items()) + list(spec.get("optional", {}).items())
        wv = list(n.get("widgets_values") or [])
        linked = {i["name"]: i.get("link") for i in n.get("inputs", [])}
        inputs, k = {}, 0
        for name, s in order:
            if is_widget(s):
                if k < len(wv):
                    inputs[name] = wv[k]
                k += 1
                opts = s[1] if len(s) > 1 and isinstance(s[1], dict) else {}
                if opts.get("control_after_generate") or name in ("seed", "noise_seed"):
                    k += 1  # 'randomize'/'fixed' value lives only in the UI
                if opts.get("image_upload"):
                    k += 1  # upload button value
            if linked.get(name) is not None:
                l = links[linked[name]]
                inputs[name] = [str(l[1]), l[2]]
        if k != len(wv):
            raise SystemExit(f"{n['type']} #{n['id']}: used {k} widget values, file has {len(wv)}")
        out[str(n["id"])] = {"class_type": n["type"], "inputs": inputs,
                             "_meta": {"title": n.get("title") or n["type"]}}
    return out

if __name__ == "__main__":
    info = json.load(open(sys.argv[1]))
    ui = json.load(open(sys.argv[2]))
    json.dump(convert(ui, info), open(sys.argv[3], "w", encoding="utf-8"), ensure_ascii=False, indent=1)
