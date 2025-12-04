import os
import sys
import bpy
import math
import shutil
import platform
import subprocess
import json
from properties.SpriteSheetPropertyGroup import SpriteSheetPropertyGroup
from properties.ProgressPropertyGroup import ProgressPropertyGroup

platform_sys = platform.system()
if platform_sys == "Windows":
    ASSEMBLER_FILENAME = "assembler.exe"
elif platform_sys == "Linux":
    ASSEMBLER_FILENAME = "assembler_linux"
else:
    ASSEMBLER_FILENAME = "assembler_mac"

def frame_count(frame_range):
    frameMin = math.floor(frame_range[0])
    frameMax = math.ceil(frame_range[1])
    return (frameMax - frameMin, frameMin, frameMax)

class RenderSpriteSheet(bpy.types.Operator):
    """Operator used to render sprite sheets for an object"""
    bl_idname = "spritesheets.render"
    bl_label = "Render Sprite Sheets"
    bl_description = "Renders all actions to a single sprite sheet"

    # --- State Variables ---
    _timer = None
    _actions = []          # List of all actions to process
    _action_index = 0      # Current action we are working on
    _frame_queue = []      # List of specific frame numbers to render for current action
    _frame_queue_index = 0 # Current position in the frame queue
    _animation_descs = []  # Data to save to JSON later
    _global_frame_end = 0  # Tracking total frames for JSON

    def invoke(self, context, event):
        scene = context.scene
        props = scene.SpriteSheetPropertyGroup
        progressProps = scene.ProgressPropertyGroup
        
        # 1. Initialization
        progressProps.rendering = True
        progressProps.success = False
        progressProps.actionTotal = len(bpy.data.actions)
        
        self._actions = list(bpy.data.actions)
        self._action_index = 0
        self._animation_descs = []
        self._global_frame_end = 0
        
        # 2. Setup the first action
        if not self._actions:
            self.report({'WARNING'}, "No actions found")
            return {'CANCELLED'}
            
        self.setup_next_action(context)

        # 3. Start the Timer (Runs every 0.01 seconds)
        wm = context.window_manager
        self._timer = wm.event_timer_add(0.01, window=context.window)
        wm.modal_handler_add(self)
        
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # Allow user to cancel with ESC
        if event.type == 'ESC':
            return self.cancel(context)

        if event.type == 'TIMER':
            # Process one step
            self.process_step(context)
            
            # Update UI
            if context.area:
                context.area.tag_redraw()
            
            # Check if we are completely done
            if self._action_index >= len(self._actions):
                self.finish(context)
                return {'FINISHED'}

        return {'PASS_THROUGH'}

    def setup_next_action(self, context):
        """Prepares the next action and generates the list of frames to render for it."""
        scene = context.scene
        props = scene.SpriteSheetPropertyGroup
        progressProps = scene.ProgressPropertyGroup
        
        current_action = self._actions[self._action_index]
        objectToRender = props.target
        
        # Update UI Data
        progressProps.actionName = current_action.name
        progressProps.actionIndex = self._action_index
        
        # Set the action on the object
        objectToRender.animation_data.action = current_action

        # Determine which frames to render (Marked vs Range)
        self._frame_queue = []
        self._frame_queue_index = 0
        
        actionPoseMarkers = current_action.pose_markers
        
        # LOGIC: Populate _frame_queue based on your original settings
        if props.onlyRenderMarkedFrames is True and actionPoseMarkers and len(actionPoseMarkers) > 0:
            # Case A: Marked Frames
            for marker in actionPoseMarkers.values():
                self._frame_queue.append(marker.frame)
        else:
            # Case B: Frame Range
            _, frameMin, frameMax = frame_count(current_action.frame_range)
            self._frame_queue = list(range(frameMin, frameMax + 1))

        # Update Total Tiles count for the progress bar
        progressProps.tileTotal = len(self._frame_queue)

        # Calculate metadata for JSON (width of the action)
        count, _, _ = frame_count(current_action.frame_range)
        self._global_frame_end += count
        
        self._animation_descs.append({
            "name": current_action.name,
            "end": self._global_frame_end,
        })

    def process_step(self, context):
        """Renders exactly ONE frame."""
        # If we have finished the current action's frames
        if self._frame_queue_index >= len(self._frame_queue):
            # Move to next action
            self._action_index += 1
            if self._action_index < len(self._actions):
                self.setup_next_action(context)
            return

        # Get current frame number
        frame_num = self._frame_queue[self._frame_queue_index]
        
        # Update Scene and UI
        context.scene.frame_set(frame_num)
        context.scene.ProgressPropertyGroup.tileIndex = frame_num # or self._frame_queue_index for 0-N progress
        
        # --- THE RENDER CALL ---
        # This still blocks, but only for ONE frame. 
        # Blender will respond to inputs immediately after this line finishes.
        bpy.ops.spritesheets.render_tile('EXEC_DEFAULT')
        
        # Increment for next loop
        self._frame_queue_index += 1

    def finish(self, context):
        """Called when all renders are done. Runs assembler and saves JSON."""
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        
        scene = context.scene
        props = scene.SpriteSheetPropertyGroup
        progressProps = scene.ProgressPropertyGroup
        objectToRender = props.target

        # --- Assembler Logic ---
        assemblerPath = os.path.normpath(
            os.path.join(props.binPath, ASSEMBLER_FILENAME)
        )
        print("Assembler path: ", assemblerPath)
        
        # Note: This subprocess is still blocking, but usually fast.
        subprocess.run([assemblerPath, "--root", bpy.path.abspath(props.outputPath), "--out", objectToRender.name + ".png"])

        # --- JSON Logic ---
        json_info = {
            "name": objectToRender.name,
            "tileWidth": props.tileSize[0],
            "tileHeight": props.tileSize[1],
            "frameRate": props.fps,
            "animations": self._animation_descs,
        }

        with open(bpy.path.abspath(os.path.join(props.outputPath, objectToRender.name + ".bss")), "w") as f:
            json.dump(json_info, f, indent='\t')

        # Cleanup
        progressProps.rendering = False
        progressProps.success = True
        
        temp_path = bpy.path.abspath(os.path.join(props.outputPath, "temp"))
        if os.path.exists(temp_path):
            shutil.rmtree(temp_path)

    def cancel(self, context):
        wm = context.window_manager
        wm.event_timer_remove(self._timer)
        context.scene.ProgressPropertyGroup.rendering = False
        self.report({'INFO'}, "Render Cancelled")
        return {'CANCELLED'}