"""Read only material alpha from installed Unity resources or embedded GLB images."""

import io

import numpy as np
from PIL import Image

from dale.alchemist_alpha import (
    MAX_ALPHA_BYTES,
    MAX_TEXTURE_BYTES,
    MAX_TEXTURE_PIXELS,
    AlphaSurface,
    alpha_channel,
)


def remember(cache, key, image):
    value = alpha_channel(image)
    if sum(a.nbytes for a in cache.values()) + value.nbytes > MAX_ALPHA_BYTES:
        raise ValueError("Model alpha channels exceed the supported memory budget.")
    cache[key] = value
    return value


def native_alpha(texture, root):
    """Seek the referenced local byte range, never load/cache the entire resS file."""
    from UnityPy.export.Texture2DConverter import parse_image_data

    if not 0 < texture.m_Width * texture.m_Height <= MAX_TEXTURE_PIXELS:
        raise ValueError("Model texture exceeds the supported size.")
    raw = texture.image_data
    if not raw:
        stream = texture.m_StreamData
        size, offset = stream.size, stream.offset
        if not 0 < size <= MAX_TEXTURE_BYTES or offset < 0:
            raise ValueError("Invalid model texture resource range.")
        # Unity resources name their local sibling file. Do not follow arbitrary paths.
        name = str(stream.path).replace("\\", "/").rsplit("/", 1)[-1]
        path = (root / name).resolve()
        if path.parent != root.resolve():
            raise ValueError("Invalid local texture resource.")
        with path.open("rb") as source:
            source.seek(offset)
            raw = source.read(size)
        if len(raw) != size:
            raise ValueError("Incomplete local texture resource.")
    if len(raw) > MAX_TEXTURE_BYTES:
        raise ValueError("Model texture exceeds the supported size.")
    reader = texture.object_reader
    return parse_image_data(
        raw,
        texture.m_Width,
        texture.m_Height,
        texture.m_TextureFormat,
        reader.version,
        reader.platform,
        texture.m_PlatformBlob,
        flip=False,
    )


def native_surface(material, uv, root, cache):
    if material is None:
        return None
    floats = dict(material.m_SavedProperties.m_Floats)
    keywords = set((material.m_ShaderKeywords or "").split())
    keywords.update(getattr(material, "m_ValidKeywords", None) or ())
    cutout = (
        floats.get("_Mode") == 1 or floats.get("_AlphaClip", 0) != 0 or "_ALPHATEST_ON" in keywords
    )
    transparent = (
        floats.get("_Mode", 0) >= 2
        or floats.get("_Surface", 0) != 0
        or bool(keywords & {"_ALPHABLEND_ON", "_ALPHAPREMULTIPLY_ON"})
    )
    if not cutout and not transparent:
        return None
    textures = dict(material.m_SavedProperties.m_TexEnvs)
    texture_env = next(
        (
            textures[name]
            for name in ("_BaseMap", "_MainTex")
            if name in textures and textures[name].m_Texture.m_PathID
        ),
        None,
    )
    colors = dict(material.m_SavedProperties.m_Colors)
    tint = colors.get("_BaseColor", colors.get("_Color"))
    opacity = float(tint.a) if tint else 1.0
    cutoff = float(floats.get("_Cutoff", 0.5)) if cutout else 1 / 255
    wrap = ("repeat", "repeat")
    coordinates = np.asarray(uv, dtype=float)
    if texture_env is None:
        if opacity >= cutoff:
            return None
        alpha = np.zeros((1, 1), dtype=np.uint8)
    else:
        reader = texture_env.m_Texture.deref()
        key = (reader.assets_file.name, reader.path_id)
        texture = reader.read()
        if key not in cache:
            with native_alpha(texture, root) as image:
                remember(cache, key, image)
        alpha = cache[key]
        coordinates = coordinates * (texture_env.m_Scale.x, texture_env.m_Scale.y)
        coordinates += (texture_env.m_Offset.x, texture_env.m_Offset.y)
        settings = texture.m_TextureSettings
        wrap = tuple(
            {0: "repeat", 1: "clamp", 2: "mirror"}[v] for v in (settings.m_WrapU, settings.m_WrapV)
        )
    return AlphaSurface(coordinates, alpha, cutoff, opacity, wrap)


def glb_surface(document, binary, material, attributes, accessor, cache):
    mode = material.get("alphaMode", "OPAQUE")
    if mode == "OPAQUE":
        return None
    if mode not in ("MASK", "BLEND"):
        raise ValueError("Unsupported GLB alpha mode.")
    pbr = material.get("pbrMetallicRoughness", {})
    opacity = pbr.get("baseColorFactor", (1, 1, 1, 1))[3]
    cutoff = material.get("alphaCutoff", 0.5) if mode == "MASK" else 1 / 255
    info = pbr.get("baseColorTexture")
    wrap = ("repeat", "repeat")
    if info is None:
        if opacity >= cutoff:
            return None
        uv = np.zeros((len(accessor(attributes["POSITION"], True)), 2))
        return AlphaSurface(uv, np.zeros((1, 1), dtype=np.uint8), cutoff, opacity)
    if info.get("extensions"):
        raise ValueError("Unsupported GLB texture extension.")
    texture = document["textures"][info["index"]]
    key = texture["source"]
    if key not in cache:
        image = document["images"][key]
        if image.get("uri") or "bufferView" not in image:
            raise ValueError("External model textures are unsupported.")
        view = document["bufferViews"][image["bufferView"]]
        start, size = view.get("byteOffset", 0), view["byteLength"]
        if (
            view.get("buffer", 0)
            or start < 0
            or not 0 < size <= MAX_TEXTURE_BYTES
            or start + size > len(binary)
        ):
            raise ValueError("Invalid model image range.")
        with Image.open(io.BytesIO(binary[start : start + size])) as decoded:
            if decoded.format not in ("PNG", "JPEG"):
                raise ValueError("Unsupported GLB image format.")
            remember(cache, key, decoded)
    sampler = document.get("samplers", [])[texture["sampler"]] if "sampler" in texture else {}
    wrap = tuple(
        {10497: "repeat", 33071: "clamp", 33648: "mirror"}[sampler.get(k, 10497)]
        for k in ("wrapS", "wrapT")
    )
    uv = accessor(attributes[f"TEXCOORD_{info.get('texCoord', 0)}"], width=2)
    return AlphaSurface(uv, cache[key], cutoff, opacity, wrap)
