"""
debug.py

Scans all `.po` files in the `translated/` folder and fixes entries according to
a single configuration variable `FORBIDDEN` (a list of strings). For any forbidden
string found inside a `msgid` the script will ensure that the corresponding
`msgstr` preserves the forbidden substring exactly (or revert the whole entry if
`msgid` equals the forbidden string).

Behavior (conservative):
- If a forbidden token is exactly the entire `msgid` -> set `msgstr = msgid`.
- If a forbidden token appears anywhere inside `msgid`:
  - If `msgstr` already contains the exact token -> leave as-is.
  - If `msgstr` does not contain the token:
    - If `msgstr` is empty -> set `msgstr = msgid`.
    - Else -> insert the exact token into `msgstr` at a roughly corresponding
      position (heuristic: same relative index) so UE tokens are preserved.

The script will modify PO files in-place. No automatic `.bak` backups are created.

Usage (PowerShell):
.venv\Scripts\python.exe debug.py

Note: this uses `polib` to parse and write PO files. Install it if missing:
pip install polib

Edit the FORBIDDEN list below to customize the tokens you don't want translated.
"""

import sys
from pathlib import Path
import shutil
import difflib

# Single configuration variable: list of forbidden substrings (case-sensitive by default)
# Edit this list as needed. Matches are performed using plain substring search.
FORBIDDEN = [
    "freesound.org",
    "team Galactic Games",
    "Galactic Games",
    "GalacticGames",
    "Daniel Seman",
    "r.setres",
    "r.ScreenPercentage",
    "r.VSync",
    "t.MaxFPS",
    "sg.TextureQuality",
    "DanielSeman",
    "stat fps",
    "stat unit",
    "stat unitgraph",
    "stat scenerendering",
    "stat rhi",
    "stat gpu",
    "stat memory",
    "stat game",
    "stat engine",
    "stat slate",
    "stat slatememory",
    "r.shadowquality",
    "r.viewdistancescale",
    "r.screenpercentage",
    "r.vsync",
    "t.maxfps",
    "sg.texturequality",
    "sg.shadowquality",
    "sg.anti-aliasingquality",
    "sg.postprocessquality",
    "sg.effectsquality",
    "sg.foliagequality",
    "sg.viewdistancequality",
    "r.tonemapper.quality",
    "r.reflections.quality",
    "r.globallillumination.quality",
    "r.raytracing.quality",
    "r.raytracing.reflections",
    "r.raytracing.shadows",
    "r.lightmapquality",
    "r.dynamicglobalillumination",
    "r.lumen.quality",
    "r.lumen.reflections",
    "r.lumen.gi",
    "r.volumetricfog",
    "r.volumetriccloud",
    "p.visualizecollision",
    "p.visualizephysics",
    "show collision",
    "show navigation",
    "stat physics",
    "ai.debug.drawnavigation",
    "ai.debug.showcrowd",
    "nav.debug.drawopen",
    "show debug",
    "show flags",
    "stat ui",
    "stat uobjects",
    "toggledebugcamera",
    "behindview",
    "cameraset",
    "show playercontroller",
    "stat net",
    "stat netstats",
    "net.debug.csenabled",
    "net.debug.clientcorrection",
    "au.debug.sounds",
    "stat audio",
    "show audioradius",
    "a.debug.draw.skeleton",
    "show bones",
    "stat animation",
    "stat animdeps",
    "streaming.levels",
    "stat streaming",
    "show streaming",
    "flushshadercache",
    "dumpmaterials",
    "stat materials",
    "stat shaders",
    "Editor.StopPlaySession",
    "Editor.PausePlaySession",
    "Editor.ResumePlaySession",
    "MODE",
    "BUILD",
    "log list",
    "debug break",
    "obj list",
    "obj gc",
    "mem report",
    "travel",
    "Execute Console Command",
    "Print String",
    "Print Text",
    "Draw Debug Line",
    "Draw Debug Sphere",
    "Draw Debug Box",
    "UnrealEditor.exe",
    "-buildmachine",
    "-skipcompile",
    "-fullrebuild",
    # Nové příkazy z dokumentu
    "r.setres 7680x4320",
    "r.setres 5120x3840",
    "r.setres 1920x1080",
    "r.setres 1600x900",
    "r.setres 1366x768",
    "r.setres 1280x720",
    "r.setres 800x600",
    "r.setres 720x480",
    "r.setres 5120x3200",
    "r.setres 5120x2880",
    "r.setres 3840x2160",
    "r.setres 3440x1440",
    "r.setres 3200x1800",
    "r.setres 2560x1440",
    "r.setres 2560x1080",
    "r.setres 1920x1200",
    "r.setres 640x480",
    "r.ScreenPercentage 25",
    "r.ScreenPercentage 50",
    "r.ScreenPercentage 75",
    "r.ScreenPercentage 100",
    "r.VSync 1",
    "r.VSync 0",
    "sg.ViewDistanceQuality 0",
    "sg.ViewDistanceQuality 1",
    "sg.ViewDistanceQuality 2",
    "sg.ViewDistanceQuality 3",
    "sg.ViewDistanceQuality 4",
    "sg.EffectsQuality 0",
    "sg.EffectsQuality 1",
    "sg.EffectsQuality 2",
    "sg.EffectsQuality 3",
    "sg.EffectsQuality 4",
    "sg.PostProcessQuality 0",
    "sg.PostProcessQuality 1",
    "sg.PostProcessQuality 2",
    "sg.PostProcessQuality 3",
    "sg.ShadowQuality 0",
    "sg.ShadowQuality 1",
    "sg.ShadowQuality 2",
    "sg.ShadowQuality 3",
    "sg.TextureQuality 0",
    "sg.TextureQuality 1",
    "sg.TextureQuality 2",
    "sg.TextureQuality 3",
    "sg.TextureQuality 4",
    "t.MaxFPS 15",
    "t.MaxFPS 30",
    "t.MaxFPS 60",
    "t.MaxFPS 120",
    "t.MaxFPS 144",
    "t.MaxFPS 9999",
    "r.ReflectionMethod 0",
    "r.ReflectionMethod 1",
    "r.ReflectionMethod 2",
    "r.ReflectionMethod 3",
    "r.TonemapperGamma",
    "r.TonemappertGamma 0",
    "server travel",
    "travel",
    "stat fps",
    "stat unit",
    "stat unitgraph",
    "stat scenerendering",
    "stat rhi",
    "stat gpu",
    "stat memory",
    "stat game",
    "stat engine",
    "stat slate",
    "stat slatememory",
    "stat physics",
    "stat ui",
    "stat uobjects",
    "stat net",
    "stat netstats",
    "stat audio",
    "stat animation",
    "stat animdeps",
    "stat streaming",
    "stat materials",
    "stat shaders",
    "show collision",
    "show navigation",
    "show debug",
    "show flags",
    "show playercontroller",
    "show audioradius",
    "show bones",
    "show streaming",
    "ai.debug.drawnavigation",
    "ai.debug.showcrowd",
    "nav.debug.drawopen",
    "p.visualizecollision",
    "p.visualizephysics",
    "net.debug.csenabled",
    "net.debug.clientcorrection",
    "au.debug.sounds",
    "a.debug.draw.skeleton",
    "flushshadercache",
    "dumpmaterials",
    "obj list",
    "obj gc",
    "toggledebugcamera",
    "behindview"
    
    # Renderování a grafika
    "r.DepthOfFieldQuality",
    "r.MotionBlurQuality",
    "r.AmbientOcclusionLevels",
    "r.SSR.Quality",
    "r.BloomQuality",
    "r.LensFlareQuality",
    "r.SceneColorFormat",
    "r.FullScreenMode",
    "r.DefaultFeature.AntiAliasing",
    "r.MSAA.CompositingSampleCount",
    "r.TemporalAASamples",
    "r.TemporalAACurrentFrameWeight",
    "r.Tonemapper.Sharpen",
    "r.Color.Mid",
    "r.Color.Gamma",
    "r.DynamicResolution",
    
    # Světlo a stíny
    "r.Shadow.CSM.MaxCascades",
    "r.Shadow.MaxResolution",
    "r.Shadow.RadiusThreshold",
    "r.Shadow.DistanceScale",
    "r.Shadow.CSM.TransitionScale",
    "r.Shadow.PreShadowResolutionFactor",
    "r.Shadow.MinResolution",
    
    # Post-process efekty
    "r.Bloom.Intensity",
    "r.Bloom.Threshold",
    "r.DepthOfField.FocalDistance",
    "r.DepthOfField.DepthBlurRadius",
    "r.VignetteIntensity",
    "r.GrainIntensity",
    "r.ChromaticAberration.StartOffset",
    "r.ChromaticAberration.Max",
    
    # Lumen a globální osvětlení
    "r.Lumen.DiffuseIndirect",
    "r.Lumen.Reflections",
    "r.Lumen.ScreenTraces",
    "r.Lumen.Detail",
    "r.Lumen.Visualize",
    "r.GlobalIllumination",
    "r.DynamicGlobalIlluminationMethod",
    
    # Nanite
    "r.Nanite",
    "r.Nanite.Visualize",
    "r.Nanite.MaxPixelsPerEdge",
    "r.Nanite.Streaming",
    
    # Virtual Shadow Maps
    "r.Shadow.Virtual.Enable",
    "r.Shadow.Virtual.ResolutionLodBias",
    "r.Shadow.Virtual.SMRT",
    
    # Foliage
    "foliage.DensityScale",
    "foliage.LODDistanceScale",
    "foliage.ForceLOD",
    
    # Partikly a efekty
    "fx.Niagara.SimCache",
    "fx.Niagara.Debug",
    "fx.Decal",
    "r.VolumetricFog",
    "r.VolumetricCloud",
    "r.VolumetricRenderTarget",
    
    # AI a navigace
    "ai.NavMesh.Draw",
    "ai.NavMesh.DrawBits",
    "ai.Crowd.Debug",
    "ai.Debug.Draw",
    "ai.Debug.Goals",
    
    # Fyzika
    "p.Gravity",
    "p.RigidBodyMaxAngularVelocity",
    "physics.Bodies.EnableGravity",
    "physics.Contacts.Draw",
    
    # Zvuk
    "au.3d.Debug",
    "au.Reverb",
    "au.Volume",
    "au.StreamCacheSize",
    
    # UI a HUD
    "ui.Draw",
    "hud.Draw",
    "hud.Debug",
    
    # Animace
    "a.URO.Enable",
    "a.EnableAnimationBlueprints",
    "a.DrawDebugSkeleton",
    "a.DrawDebugBones",
    
    # Materiály
    "r.MaterialQualityLevel",
    "r.Shaders.Optimize",
    "r.Shaders.KeepDebugInfo",
    "r.CompileShaders",
    
    # Streaming a úrovně
    "streaming.PoolSize",
    "streaming.UseFixedPoolSize",
    "streaming.HLODs",
    "level.Load",
    "level.Unload",
    
    # Síťování a multiplayer
    "net.AllowPlayer",
    "net.Kick",
    "net.Ban",
    "net.ServerTravel",
    "net.ClientTravel",
    "net.Pause",
    "net.Restart",
    "net.Speed",
    
    # Debug a profiling
    "profilegpu",
    "profilecpu",
    "profilergpu",
    "stat scenerendering",
    "stat initviews",
    "stat game",
    "stat engine",
    "stat slate",
    "stat unitgraph",
    "stat rhi",
    "stat memory",
    "stat streaming",
    "stat anim",
    "stat audio",
    "stat physics",
    "stat net",
    "stat ui",
    
    # Kamera
    "camera.fov",
    "camera.freeze",
    "camera.unfreeze",
    
    # Skrytí UI
    "ui.hidden",
    
    # Blueprint a skriptování
    "blueprint.debug",
    "kismet.debug",
    "script.pause",
    "script.resume",
    
    # VR a speciální módy
    "vr.Enable",
    "vr.mirror",
    "stereo.on",
    "stereo.off",
    
    # Příkazy specifické pro editory
    "Editor.Mode",
    "Editor.Play",
    "Editor.Stop",
    "Editor.Pause",
    "Editor.Build",
    "Editor.Cook",
    "Editor.Package"
]

# Path settings
BASE = Path(__file__).resolve().parent
PO_DIR = BASE / 'translated'

# Try to import polib
try:
    import polib
except Exception:
    print("polib not installed. Please install with: pip install polib")
    sys.exit(1)


def find_forbidden_in_text(text: str):
    """Return list of forbidden tokens found in text (exact substring match).
    Matches are case-sensitive; adjust by lowercasing both sides if you want.
    """
    found = []
    if not text:
        return found
    for token in FORBIDDEN:
        if token and token in text:
            found.append(token)
    return found


def insert_token_preserve(translated: str, token: str, orig: str):
    """Ensure `token` appears in `translated`. If already present, return translated.
    Otherwise, insert token at a heuristic position corresponding to token's
    position in `orig`.
    """
    if token in translated:
        return translated
    if not translated:
        return orig
    # Compute approximate insertion index by ratio of token start in orig
    start = orig.find(token)
    if start == -1:
        # fallback: append
        return translated + ' ' + token
    ratio = start / max(1, len(orig))
    ins_idx = int(ratio * len(translated))
    # Insert with spaces around if necessary
    left = translated[:ins_idx].rstrip()
    right = translated[ins_idx:].lstrip()
    if left:
        left = left + ' '
    if right:
        token_with = token + ' '
    else:
        token_with = token
    return left + token_with + right


def process_po_file(po_path: Path):
    print(f"Processing {po_path}")
    po = polib.pofile(str(po_path))
    changed = False
    for entry in po:
        if not entry.msgid:
            continue
        orig = entry.msgid
        trans = entry.msgstr
        found = find_forbidden_in_text(orig)
        if not found:
            continue
        # For each forbidden token present in the msgid, ensure it's preserved in msgstr
        for token in found:
            # Exact whole-text match -> set msgstr = msgid
            if orig.strip() == token.strip():
                if trans != orig:
                    print(f"  Reverting whole entry for token '{token}'")
                    entry.msgstr = orig
                    changed = True
                continue
            # If token already present in translation, skip
            if token in trans:
                continue
            # If translation is empty, set to original (conservative)
            if not trans.strip():
                print(f"  Empty translation -> setting msgstr = msgid for token '{token}'")
                entry.msgstr = orig
                changed = True
                continue
            # Otherwise insert token into translated text heuristically
            new_trans = insert_token_preserve(trans, token, orig)
            if new_trans != trans:
                print(f"  Restoring token '{token}' into translation (approx position)")
                entry.msgstr = new_trans
                changed = True
    #if changed:
        # backup and write
        #bak = po_path.with_suffix(po_path.suffix + '.bak')
        #print(f"  Changes detected, backing up original to {bak}")
        #shutil.copy2(str(po_path), str(bak))
        #po.save(str(po_path))
    #else:
        #print("  No changes needed")


def main():
    if not PO_DIR.exists() or not PO_DIR.is_dir():
        print(f"Translated .po directory not found: {PO_DIR}")
        sys.exit(1)
    po_files = list(PO_DIR.glob('*.po'))
    if not po_files:
        print(f"No .po files found in {PO_DIR}")
        return
    for p in po_files:
        process_po_file(p)

if __name__ == '__main__':
    main()
