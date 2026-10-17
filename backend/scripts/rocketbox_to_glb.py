"""A Microsoft Rocketbox avatar (MIT) as one GLB the teacher page can load.

    blender -b --python backend/scripts/rocketbox_to_glb.py -- AVATAR_DIR OUT.glb

AVATAR_DIR is an avatar's folder from github.com/microsoft/Microsoft-Rocketbox
(Export/<name>_facial.fbx and Textures/*.tga). The facial version carries the
15 speech visemes and the ARKit expressions the teacher uses. This keeps only
those shapes, rebuilds the materials from the textures (base colour, normal
map, the eyelashes' opacity), shrinks the textures to 1024 px JPEGs and
writes a binary glTF with the skeleton and the shape keys: a few MB.
"""
from __future__ import annotations

import glob
import os
import sys

import bpy

KEEP = (
    # Speech: the Oculus viseme set.
    "AA_VI_",
    # Expressions: blinks, brows, smiles, eyes, jaw.
    "AK_01_BrowDownLeft", "AK_02_BrowDownRight", "AK_03_BrowInnerUp", "AK_04_BrowOuterUpLeft",
    "AK_05_BrowOuterUpRight", "AK_07_CheekSquintLeft", "AK_08_CheekSquintRight", "AK_09_EyeBlinkLeft",
    "AK_10_EyeBlinkRight", "AK_11_EyeLookDownLeft", "AK_12_EyeLookDownRight", "AK_13_EyeLookInLeft",
    "AK_14_EyeLookInRight", "AK_15_EyeLookOutLeft", "AK_16_EyeLookOutRight", "AK_17_EyeLookUpLeft",
    "AK_18_EyeLookUpRight", "AK_19_EyeSquintLeft", "AK_20_EyeSquintRight", "AK_21_EyeWideLeft",
    "AK_22_EyeWideRight", "AK_25_JawOpen", "AK_27_MouthClose", "AK_30_MouthFrownLeft", "AK_31_MouthFrownRight",
    "AK_44_MouthSmileLeft", "AK_45_MouthSmileRight",
)
SIZE = 1024


def main() -> None:
    args = sys.argv[sys.argv.index("--") + 1:]
    folder, out = args[0], args[1]
    fbx = glob.glob(os.path.join(folder, "Export", "*_facial.fbx"))[0]
    textures = {os.path.basename(p)[:-4]: p for p in glob.glob(os.path.join(folder, "Textures", "*.tga"))}

    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.fbx(filepath=fbx)

    for obj in [o for o in bpy.data.objects if o.type == "MESH"]:
        keys = obj.data.shape_keys
        if keys:
            for kb in list(keys.key_blocks)[1:]:
                if not kb.name.startswith(KEEP):
                    obj.shape_key_remove(kb)
            print(obj.name, "shape keys kept:", len(obj.data.shape_keys.key_blocks) - 1)
        for slot in obj.material_slots:
            if slot.material:
                rebuild(slot.material, textures)

    for img in bpy.data.images:
        if img.size[0] > SIZE:
            img.scale(SIZE, SIZE)

    bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_image_format="JPEG", export_jpeg_quality=82,
                              export_skins=True, export_morph=True, export_morph_normal=False,
                              export_animations=False, export_yup=True)
    print("wrote", out, round(os.path.getsize(out) / 1e6, 2), "MB")


def rebuild(mat: bpy.types.Material, textures: dict[str, str]) -> None:
    """A Principled material from <name>_color / _normal / opacity textures."""
    prefix = mat.name.split(".")[0]                       # f014_body, f014_head, f014_opacity
    mat.use_nodes = True
    nodes, links = mat.node_tree.nodes, mat.node_tree.links
    nodes.clear()
    out = nodes.new("ShaderNodeOutputMaterial")
    bsdf = nodes.new("ShaderNodeBsdfPrincipled")
    links.new(bsdf.outputs["BSDF"], out.inputs["Surface"])
    bsdf.inputs["Roughness"].default_value = 0.5 if "head" in prefix else 0.62

    def image(name: str, colour: bool):
        path = textures.get(name)
        if not path:
            return None
        node = nodes.new("ShaderNodeTexImage")
        node.image = bpy.data.images.load(path, check_existing=True)
        node.image.colorspace_settings.name = "sRGB" if colour else "Non-Color"
        return node

    colour = image(f"{prefix}_color", True)
    if colour:
        links.new(colour.outputs["Color"], bsdf.inputs["Base Color"])
        if "opacity" in prefix:
            links.new(colour.outputs["Alpha"], bsdf.inputs["Alpha"])
    normal = image(f"{prefix}_normal", False)
    if normal:
        nm = nodes.new("ShaderNodeNormalMap")
        links.new(normal.outputs["Color"], nm.inputs["Color"])
        links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])


main()
