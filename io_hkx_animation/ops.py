import math
import os
import subprocess

import bpy
from bpy_extras.io_utils import axis_conversion
import bpy_extras
import mathutils

from .ixml import DocumentInterface
from .ixml import ReferenceFrame
from .ixml import Track
from .prefs import EXEC_NAME
from .props import AXES

FRAMERATE_OPTIONS = [
    ("30", "30 FPS", "Standard Havok framerate"),
    ("60", "60 FPS", "High framerate for smoother animations"),
    ("120", "120 FPS", "Very high framerate for ultra-smooth animations"),
    ("240", "240 FPS", "Ultra high framerate for maximum smoothness"),
]


def get_sampling_rate(operator):
    """Get the current sampling rate from the operator"""
    return int(operator.framerate)


class HKXIO(bpy.types.Operator):
    length_scale: bpy.props.FloatProperty(
        name="Length scale", description="Scale factor for length units", default=10.0
    )

    primary_skeleton: bpy.props.StringProperty(
        name="Primary skeleton",
        description="Path to the HKX skeleton file (can be relative to .blend file)",
    )

    secondary_skeleton: bpy.props.StringProperty(
        name="Secondary skeleton",
        description="Path to the skeleton of the second actor in a paired animation (can be relative to .blend file)",
    )

    bone_forward: bpy.props.EnumProperty(
        items=AXES,
        name="Forward axis",
        description="This axis will be mapped to Blender's Y axis",
        default="Y",
        # update=callbackfcn
    )

    bone_up: bpy.props.EnumProperty(
        items=AXES,
        name="Up axis",
        description="This axis will be mapped to Blender's Z axis",
        default="Z",
        # update=callbackfcn
    )

    def resolve_skeleton_path(self, path):
        """Convert relative paths to absolute paths based on the current .blend file location"""
        if not path:
            return path

        # If path is already absolute, return as-is
        if os.path.isabs(path):
            return path

        # Get the directory of the current .blend file
        blend_filepath = bpy.data.filepath
        if not blend_filepath:
            # No .blend file is open, return path as-is
            return path

        blend_dir = os.path.dirname(blend_filepath)
        # Resolve the relative path
        resolved_path = os.path.join(blend_dir, path)
        return os.path.normpath(resolved_path)

    def get_resolved_skeleton_paths(self):
        """Get both skeleton paths resolved to absolute paths"""
        primary_resolved = self.resolve_skeleton_path(self.primary_skeleton)
        secondary_resolved = self.resolve_skeleton_path(self.secondary_skeleton)
        return primary_resolved, secondary_resolved

    def init_settings(self, context):
        # set skeleton path(s) to that of the active armature(s) (default if none)

        # primary is the active armature
        active = context.view_layer.objects.active

        if active and active.type == "ARMATURE":
            self.length_scale = active.data.iohkx.length_scale
            self.primary_skeleton = active.data.iohkx.skeleton_path
            self.bone_forward = active.data.iohkx.bone_forward
            self.bone_up = active.data.iohkx.bone_up

        # default if none
        if self.primary_skeleton == "":
            self.primary_skeleton = context.preferences.addons[
                __package__
            ].preferences.default_skeleton

        # secondary is the first non-active armature
        selected = context.view_layer.objects.selected
        for obj in selected:
            if obj.type == "ARMATURE" and obj != active:
                self.secondary_skeleton = obj.data.iohkx.skeleton_path

                # need to decide how to store and expose the axis conventions!

                # self.bone_forward = obj.data.iohkx.bone_forward
                # self.bone_up = obj.data.iohkx.bone_up
                break

        # default if none
        if self.secondary_skeleton == "":
            self.secondary_skeleton = context.preferences.addons[
                __package__
            ].preferences.default_skeleton

    def axis_conversion(self, from_forward="Y", from_up="Z", to_forward="Y", to_up="Z"):
        # this throws if axes are invalid
        self.framerot = axis_conversion(
            from_forward=from_forward,
            from_up=from_up,
            to_forward=to_forward,
            to_up=to_up,
        ).to_4x4()
        self.framerotinv = self.framerot.transposed()

    def get_converter(self, preferences):
        pref = preferences.addons[__package__].preferences.converter_tool
        exe = os.path.join(os.path.dirname(pref), EXEC_NAME)
        if not os.path.exists(exe):
            raise RuntimeError(
                "Converter tool not found. Check your Addon Preferences."
            )

        return exe

    def get_selected(self, context):
        """Return all selected objects and all selected armatures"""
        selected = context.view_layer.objects.selected
        active = context.view_layer.objects.active

        armatures = []
        if active and active.type == "ARMATURE" and active.select_get():
            armatures.append(active)

        for obj in selected:
            if obj.type == "ARMATURE" and obj != active:
                armatures.append(obj)

        return selected, armatures

    def get_selected_export(self, context: bpy.types.Context):
        selected = list(context.view_layer.objects.selected)
        active = context.view_layer.objects.active

        # sort armatures so that the active one (if any) is first
        armatures = []

        if active and active.type == "ARMATURE":
            armatures.append(active)

        for obj in selected:
            if obj.type == "ARMATURE" and obj not in armatures:
                armatures.append(obj)

        return selected, armatures


class HKXImport(HKXIO, bpy_extras.io_utils.ImportHelper):
    bl_label = "Import"
    bl_idname = "io_hkx_animation.import"
    bl_description = "Import HKX animation"
    bl_options = {"UNDO"}

    filename_ext = ".hkx"

    filter_glob: bpy.props.StringProperty(default="*.hkx", options={"HIDDEN"})

    framerate: bpy.props.EnumProperty(
        items=FRAMERATE_OPTIONS,
        name="Animation Framerate",
        description="Framerate for HKX animation import",
        default="30",
    )

    framerot: mathutils.Matrix
    framerotinv: mathutils.Matrix

    def invoke(self, context, event):
        # get the settings and forward to ImportHelper
        self.init_settings(context)
        return bpy_extras.io_utils.ImportHelper.invoke(self, context, event)

    def execute(self, context):
        try:
            # setup axis conversion
            self.axis_conversion(from_forward=self.bone_forward, from_up=self.bone_up)

            # Set fps to sampling rate (and warn if it wasn't)
            sampling_rate = get_sampling_rate(self)
            if context.scene.render.fps != sampling_rate:
                context.scene.render.fps = sampling_rate
                self.report(
                    {"WARNING"}, "Setting framerate to %s fps" % str(sampling_rate)
                )

            # Look for the converter
            tool = self.get_converter(context.preferences)

            # Invoke the converter
            tmp_file = _tmpfilename(self.filepath, context.preferences)
            primary_resolved, secondary_resolved = self.get_resolved_skeleton_paths()
            skels = '"%s" "%s"' % (primary_resolved, secondary_resolved)
            sampling_rate = get_sampling_rate(self)
            args = '"%s" unpack %s "%s" "%s" %s' % (
                tool,
                sampling_rate,
                self.filepath,
                tmp_file,
                skels,
            )

            try:
                res = subprocess.run(args)

                # throw if the converter returned non-zero
                res.check_returncode()

                # Load the xml
                doc = DocumentInterface.open(tmp_file)

            finally:
                if os.path.exists(tmp_file):
                    os.remove(tmp_file)

            # Look up all selected armatures
            selected, armatures = self.get_selected(context)

            if len(armatures) == 0:
                # import armatures(s) from file

                # switch to object mode (not strictly required?)
                if bpy.ops.object.mode_set.poll():
                    bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

                # deselect all
                for obj in selected:
                    obj.select_set(False)

                # create new armatures
                primary_resolved, secondary_resolved = (
                    self.get_resolved_skeleton_paths()
                )
                paths = [primary_resolved, secondary_resolved]
                armatures = [
                    self.import_skeleton(i, context, p)
                    for i, p in zip(doc.skeletons, paths)
                ]
                if len(armatures) == 0:
                    raise RuntimeError("File contains no skeletons")

                # select and make active
                for arma in armatures:
                    arma.select_set(True)
                # If previously active object is excluded from the view layer, setting active fails.
                # No idea why. Fringe case, though. Move on.
                context.view_layer.objects.active = armatures[0]

            else:
                # number of selected armatures must match number of animations in the file
                n_anims = len(doc.animations)
                if len(armatures) != n_anims:
                    raise RuntimeError(
                        "Exactly %s or 0 Armatures must be selected" % (str(n_anims))
                    )

                # One armature must be selected and active
                if not context.view_layer.objects.active in armatures:
                    raise RuntimeError("Primary Armature must be active")

            # this is now guaranteed to be one of our armatures
            active_obj = context.view_layer.objects.active

            # If there are more actions than armatures, duplicate active armature
            while len(doc.animations) > len(armatures):
                # append a duplicate of armature[0]
                armatures.append(active_obj.copy())
                # they can share data, right?
                # armatures[-1].data = armatures[-1].data.copy()
                context.scene.collection.objects.link(armatures[-1])

            # create new actions
            actions = [
                self.import_animation(i, arma)
                for i, arma in zip(doc.animations, armatures)
            ]

            # add animation data if missing
            for arma in armatures:
                if not arma.animation_data:
                    arma.animation_data_create()

            # Then assign the actions
            for arma, acti in zip(armatures, actions):
                arma.animation_data.action = acti

        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, "Imported %s successfully" % self.filepath)
        return {"FINISHED"}

    def find_connected(self, bone, children):
        """Find the child (if any) that continues our bone chain, and the distance to it."""
        # A connected child should be located on our positive y axis, to within roundoff error.
        epsilon = 1e-5
        our_loc = bone.matrix.to_translation()
        for child in children:
            separation = child.matrix.to_translation() - our_loc
            # reject bones that are too close to us
            if separation.length > epsilon:
                # For separation to be parallel to our y axis, the scalar vector rejection
                # of separation from y should be less than epsilon.
                # It might be simpler to just check the angle between separation and y,
                # but that makes the error threshold slightly more complicated instead.
                assert abs(1.0 - bone.y_axis.length) < epsilon, "invalid assumption"
                scalar_projection = separation.dot(bone.y_axis)
                # reject bones on the negative side
                if scalar_projection >= 0.0:
                    rejection = separation - scalar_projection * bone.y_axis
                    if rejection.length < epsilon:
                        return child, separation.length

        # we found no connected child
        return None, None

    def import_animation(self, ianim, armature):
        # create a new action, named as file
        d, name = os.path.split(self.filepath)
        root, ext = os.path.splitext(name)
        action = bpy.data.actions.new(name=root)

        # look for bone name overrides
        overrides = {}
        for bone in armature.data.bones:
            if bone.iohkx.hkx_name != "":
                overrides[bone.iohkx.hkx_name] = bone.name

        # import the tracks
        for track in ianim.tracks():
            if track.datatype == Track.TRANSFORM:
                self.import_transform(
                    track, action, armature, overrides.get(track.name, track.name)
                )
            elif track.datatype == Track.FLOAT:
                self.import_float(track, action)

        # import markers
        for annotation in ianim.annotations():
            marker = action.pose_markers.new(annotation.text)
            marker.frame = annotation.frame

        return action

    def import_bone(self, ibone, parent, armature):
        # add bone to armature
        bone = armature.data.edit_bones.new(ibone.name)
        bone.length = 1.0

        # transform
        loc, rot, scl = ibone.reference
        loc /= self.length_scale
        mat = mathutils.Matrix.LocRotScale(loc, rot, scl)
        if parent:
            bone.parent = parent
            # bone.matrix = parent.matrix @ mat
        # else:
        # bone.matrix = mat
        bone.matrix = mat @ self.framerot

        # recurse
        children = [self.import_bone(i, bone, armature) for i in ibone.bones()]

        # axis conversion (most efficient if done leaf->root)
        # (was, until we changed the input format)
        # bone.matrix = bone.matrix @ self.framerot

        # set length
        child, length = self.find_connected(bone, children)
        if child:
            bone.length = length
        # else leave it at 1

        return bone

    def import_float(self, itrack, action):
        # create f-curve
        f = action.fcurves.new('["%s"]' % itrack.name)

        # add keys
        for key in itrack.keys():
            f.keyframe_points.insert(key.frame, key.value, options={"FAST"})

        f.update()

    def import_skeleton(self, iskeleton, context, path):
        # create armature object
        data = bpy.data.armatures.new(name=iskeleton.name)
        armature = bpy.data.objects.new(iskeleton.name, data)
        context.scene.collection.objects.link(armature)

        # store our custom properties
        data.iohkx.length_scale = self.length_scale
        data.iohkx.skeleton_path = path
        data.iohkx.bone_forward = self.bone_forward
        data.iohkx.bone_up = self.bone_up

        # start editing armature
        context.view_layer.objects.active = armature
        bpy.ops.object.mode_set(mode="EDIT", toggle=False)

        # add bones
        for ibone in iskeleton.bones():
            self.import_bone(ibone, None, armature)

        # end edit
        bpy.ops.object.mode_set(mode="OBJECT", toggle=False)

        # add float slots (custom props)
        for ifloat in iskeleton.floats():
            armature[ifloat.name] = ifloat.reference

        # display settings (optional?)
        data.display_type = "STICK"
        data.show_axes = True

        return armature

    def import_transform(self, itrack, action: bpy.types.Action, armature, name: str):
        def ensure_action_context(action: bpy.types.Action, armature: bpy.types.Object):
            """
            Ensure Slot / Layer / Keyframe Strip / ChannelBag for this action+armature.
            Returns (channelbag, slot).
            """

            # --- Slot (OBJECT, armature.name) ---
            slot = None
            for s in action.slots:
                if s.target_id_type == "OBJECT" and s.name_display == armature.name:
                    slot = s
                    break

            if slot is None:
                slot = action.slots.new(
                    id_type="OBJECT",
                    name=armature.name,
                )

            # --- Layer ---
            if action.layers:
                layer = action.layers[0]
            else:
                layer = action.layers.new("Layer")

            # --- Keyframe Strip ---
            strip = None
            for s in layer.strips:
                if s.type == "KEYFRAME":
                    strip = s
                    break

            if strip is None:
                strip = layer.strips.new(type="KEYFRAME")

            # --- ChannelBag ---
            channelbag = strip.channelbag(slot, ensure=True)

            return channelbag, slot

        armature.animation_data_create()
        armature.animation_data.action = action
        channelbag, slot = ensure_action_context(action, armature)
        fnew = channelbag.fcurves.new

        loc_x = fnew(f'pose.bones["{name}"].location', index=0, group_name=name)
        loc_y = fnew(f'pose.bones["{name}"].location', index=1, group_name=name)
        loc_z = fnew(f'pose.bones["{name}"].location', index=2, group_name=name)

        rot_w = fnew(
            f'pose.bones["{name}"].rotation_quaternion', index=0, group_name=name
        )
        rot_x = fnew(
            f'pose.bones["{name}"].rotation_quaternion', index=1, group_name=name
        )
        rot_y = fnew(
            f'pose.bones["{name}"].rotation_quaternion', index=2, group_name=name
        )
        rot_z = fnew(
            f'pose.bones["{name}"].rotation_quaternion', index=3, group_name=name
        )

        scl_x = fnew(f'pose.bones["{name}"].scale', index=0, group_name=name)
        scl_y = fnew(f'pose.bones["{name}"].scale', index=1, group_name=name)
        scl_z = fnew(f'pose.bones["{name}"].scale', index=2, group_name=name)

        for key in itrack.keys():
            # do axis and scale conversion
            loc, rot, scl = key.value
            loc /= self.length_scale
            mat = mathutils.Matrix.LocRotScale(loc, rot, scl).to_4x4()
            mat = self.framerotinv @ mat @ self.framerot
            loc, rot, scl = mat.decompose()

            # insert keyframes
            loc_x.keyframe_points.insert(key.frame, loc[0], options={"FAST"})
            loc_y.keyframe_points.insert(key.frame, loc[1], options={"FAST"})
            loc_z.keyframe_points.insert(key.frame, loc[2], options={"FAST"})

            rot_w.keyframe_points.insert(key.frame, rot[0], options={"FAST"})
            rot_x.keyframe_points.insert(key.frame, rot[1], options={"FAST"})
            rot_y.keyframe_points.insert(key.frame, rot[2], options={"FAST"})
            rot_z.keyframe_points.insert(key.frame, rot[3], options={"FAST"})

            scl_x.keyframe_points.insert(key.frame, scl[0], options={"FAST"})
            scl_y.keyframe_points.insert(key.frame, scl[1], options={"FAST"})
            scl_z.keyframe_points.insert(key.frame, scl[2], options={"FAST"})

        loc_x.update()
        loc_y.update()
        loc_z.update()

        rot_w.update()
        rot_x.update()
        rot_y.update()
        rot_z.update()

        scl_x.update()
        scl_y.update()
        scl_z.update()


FORMATS = [
    ("LE", "Skyrim", "32 bit format for the original Skyrim"),
    ("SE", "Skyrim SE", "64 bit format for Skyrim Special Edition"),
]


class HKXExport(HKXIO, bpy_extras.io_utils.ExportHelper):
    bl_label = "Export"
    bl_idname = "io_hkx_animation.export"
    bl_description = "Export animation as HKX"
    bl_options = {"UNDO"}

    filename_ext = ".hkx"

    filter_glob: bpy.props.StringProperty(
        default="*.hkx",
        options={"HIDDEN"},
    )

    framerate: bpy.props.EnumProperty(
        items=FRAMERATE_OPTIONS,
        name="Animation Framerate",
        description="Framerate for HKX animation export",
        default="30",
    )

    blend_mode: bpy.props.BoolProperty(
        name="Additive",
        description="Store offsets instead of pose",
        default=False,
    )

    frame_interval: bpy.props.IntVectorProperty(
        name="Frame interval",
        description="First and last frame of the animation",
        size=2,
        min=0,
    )

    output_format: bpy.props.EnumProperty(
        items=FORMATS,
        name="Format",
        description="Format of the output HKX file",
        default="SE",
    )

    framerot: mathutils.Matrix
    framerotinv: mathutils.Matrix

    def invoke(self, context, event):
        # get the settings and forward to ImportHelper
        self.init_settings(context)
        self.frame_interval[0] = context.scene.frame_start
        self.frame_interval[1] = context.scene.frame_end
        return bpy_extras.io_utils.ExportHelper.invoke(self, context, event)

    def execute(self, context: bpy.types.Context):  # noqa: F821
        try:
            # setup axis conversion
            self.axis_conversion(to_forward=self.bone_forward, to_up=self.bone_up)

            # Look for the converter
            tool = self.get_converter(context.preferences)

            # Look up all selected armatures
            selected, armatures = self.get_selected_export(context)

            if not armatures:
                raise RuntimeError("Needs at least one selected Armature")

            active = context.view_layer.objects.active
            if active not in armatures:
                active = armatures[0]
                context.view_layer.objects.active = active

            # fail if none
            if len(armatures) == 0 or active not in armatures:
                raise RuntimeError("Needs an active Armature")
            # fail if more than two
            if len(armatures) > 2:
                raise RuntimeError("Select at most two Armatures")

            # Look for the skeleton(s)
            primary_resolved, secondary_resolved = self.get_resolved_skeleton_paths()
            if not os.path.exists(primary_resolved):
                raise RuntimeError(
                    "Primary skeleton file not found: %s" % primary_resolved
                )
            if len(armatures) > 1 and not os.path.exists(secondary_resolved):
                raise RuntimeError(
                    "Secondary skeleton file not found: %s" % secondary_resolved
                )

            # Make sure we have frames to export
            if not self.frame_interval[1] > self.frame_interval[0]:
                raise RuntimeError("Frame interval is empty")

            # Save our custom properties
            for arma, path in zip(armatures, [primary_resolved, secondary_resolved]):
                arma.data.iohkx.length_scale = self.length_scale
                arma.data.iohkx.skeleton_path = path
                arma.data.iohkx.bone_forward = self.bone_forward
                arma.data.iohkx.bone_up = self.bone_up

            # create a document
            doc = DocumentInterface.create()

            # determine our sampling parameters
            sampling_rate = get_sampling_rate(self)
            self.framestep = context.scene.render.fps / sampling_rate
            framesteps = self.frame_interval[1] - self.frame_interval[0]

            # if framerate is not at the sampling rate, we sample at nearest possible rate and warn
            if context.scene.render.fps != sampling_rate:
                framesteps = int(round(framesteps / self.framestep))
                self.report(
                    {"WARNING"}, "Sampling animation at %s fps" % str(sampling_rate)
                )

            self.frames = framesteps + 1

            # add frame, framerate, blend mode
            doc.set_frames(self.frames)
            doc.set_framerate(sampling_rate)
            doc.set_additive(self.blend_mode)

            # add animations
            for armature in armatures:
                context.view_layer.objects.active = armature
                self.export_animation(doc, context)

            # restore active state
            context.view_layer.objects.active = active

            if len(doc.animations) != 0:
                tmp_file = _tmpfilename(self.filepath, context.preferences)
                try:
                    # write xml
                    doc.save(tmp_file)

                    # invoke converter
                    if len(doc.animations) == 1:
                        skels = '"%s"' % (primary_resolved)
                    else:
                        skels = '"%s" "%s"' % (primary_resolved, secondary_resolved)

                    if self.output_format == "LE":
                        fmt = "WIN32"
                    else:
                        fmt = "AMD64"

                    sampling_rate = get_sampling_rate(self)
                    args = '"%s" pack %s %s "%s" "%s" %s' % (
                        tool,
                        sampling_rate,
                        fmt,
                        tmp_file,
                        self.filepath,
                        skels,
                    )

                    res = subprocess.run(args)

                    # throw if the converter returned non-zero
                    res.check_returncode()

                finally:
                    os.remove(tmp_file)

        except Exception as e:
            self.report({"ERROR"}, str(e))
            return {"CANCELLED"}

        self.report({"INFO"}, "Exported %s successfully" % self.filepath)
        return {"FINISHED"}

    def export_animation(self, document, context: bpy.types.Context):
        armature = context.view_layer.objects.active

        # abort if no bones are selected
        pbones = context.selected_pose_bones_from_active_object
        if not pbones or len(pbones) == 0:
            self.report(
                {"WARNING"}, "No bones selected in %s, ignoring" % armature.name
            )
            return

        # name of animation = index
        ianim = document.add_animation(str(len(document.animations)))
        # name of skeleton = object name
        ianim.set_skeleton_name(armature.data.iohkx.skeleton_path)
        # reference frame = object
        ianim.set_reference_frame(ReferenceFrame.OBJECT)

        # use the name override (if any) as track name
        def override(pbone):
            return (
                pbone.bone.iohkx.hkx_name
                if pbone.bone.iohkx.hkx_name != ""
                else pbone.name
            )

        tracks = [ianim.add_transform_track(override(bone)) for bone in pbones]

        # we'll export only the properties that are keyframed in the current action
        slots = []
        action = armature.animation_data.action if armature.animation_data else None
        if action:
            for prop in armature.keys():
                # save this property if it has an FCurve
                fcurves = action.layers[0].strips[0].channelbag(action.slots[0]).fcurves
                if fcurves.find('["%s"]' % prop):
                    slots.append(ianim.add_float_track(prop))

        # loop over frames, add key for each track
        current_frame = context.scene.frame_current
        sampling_rate = get_sampling_rate(self)
        for i in range(self.frames):
            # set current frame (and subframe, if appropriate)
            if context.scene.render.fps == sampling_rate:
                context.scene.frame_set(self.frame_interval[0] + i)
            else:
                subframe, frame = math.modf(self.frame_interval[0] + i * self.framestep)
                context.scene.frame_set(int(frame), subframe=subframe)

            for bone, track in zip(pbones, tracks):
                # read current object-space transform
                loc, rot, scl = bone.matrix.decompose()

                # rotate to output frame
                mat = (
                    mathutils.Matrix.LocRotScale(loc, rot, scl).to_4x4() @ self.framerot
                )

                # Transform to parent-bone space
                # do this in the converter instead, less double transforming
                # if bone.parent:
                #    try:
                #        imat = (bone.parent.matrix @ self.framerot).inverted()
                #    except:
                #        raise RuntimeError("Scale must not be zero")
                #    loc, rot, scl = (imat @ mat).decompose()
                # else:
                #    loc, rot, scl = mat.decompose()

                loc, rot, scl = mat.decompose()

                # rescale length
                loc *= self.length_scale

                # add key
                key = track.add_key(i)
                key.set_value(loc, rot, scl)

            for slot in slots:
                key = slot.add_key(i)
                key.set_value(armature.get(slot.name))

        # restore state
        context.scene.frame_set(current_frame)

        # Add annotations from pose markers
        if armature.animation_data and armature.animation_data.action:
            for marker in armature.animation_data.action.pose_markers:
                if (
                    marker.frame >= self.frame_interval[0]
                    and marker.frame <= self.frame_interval[1]
                ):
                    # count from frame_interval[0]
                    i = (marker.frame - self.frame_interval[0]) / self.framestep + 1
                    ianim.add_annotation(i, marker.name)


def _tmpfilename(file_name, preferences):
    # read dir from preferences
    loc = preferences.addons[__package__].preferences.temp_location

    # Use converter dir if no temp location is set
    if loc == "":
        loc = preferences.addons[__package__].preferences.converter_tool

    root, ext = os.path.splitext(os.path.basename(file_name))
    # return loc/fileroot.tmp
    return os.path.join(loc, root) + ".tmp"


def exportop(self, context):
    self.layout.operator(HKXExport.bl_idname, text="Havok Animation (.hkx)")


def importop(self, context):
    self.layout.operator(HKXImport.bl_idname, text="Havok Animation (.hkx)")


def register():
    bpy.utils.register_class(HKXImport)
    bpy.utils.register_class(HKXExport)
    bpy.types.TOPBAR_MT_file_import.append(importop)
    bpy.types.TOPBAR_MT_file_export.append(exportop)


def unregister():
    bpy.types.TOPBAR_MT_file_export.remove(exportop)
    bpy.types.TOPBAR_MT_file_import.remove(importop)
    bpy.utils.unregister_class(HKXExport)
    bpy.utils.unregister_class(HKXImport)
