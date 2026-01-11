from . import prefs, props, ops

bl_info = {
    "name": "HKX Animation",
    "author": "Jonas Gernandt/Beefclot/COACHWICKWACK",
    "version": (1, 0, 0),
    "blender": (5, 0, 0),
    "location": "File > Import-Export",
    "description": "",
    "doc_url": "",
    "category": "Import-Export",
}


def register():
    prefs.register()
    props.register()
    ops.register()


def unregister():
    ops.unregister()
    props.unregister()
    prefs.unregister()
