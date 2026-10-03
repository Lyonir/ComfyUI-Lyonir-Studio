# Derived from ComfyUI-VideoHelperSuite by Kosinkadink and contributors.
# SPDX-License-Identifier: GPL-3.0-only
# Local adaptations: internal encoding only; packaged FFmpeg; Lyonir batch output recognition.
import os, shutil, time, server
from .logger import logger
from ..ffmpeg_runtime import get_ffmpeg_path
ffmpeg_path = get_ffmpeg_path()
gifski_path = os.environ.get('VHS_GIFSKI') or os.environ.get('JOV_GIFSKI') or shutil.which('gifski')
BIGMAX = 2**53-1
ENCODE_ARGS = ('utf-8', 'backslashreplace')
prompt_queue = server.PromptServer.instance.prompt_queue
requeue_guard = [None, 0, 0, {}]
class MultiInput(str):
    def __new__(cls, string, allowed_types="*"):
        res = super().__new__(cls, string)
        res.allowed_types=allowed_types
        return res
    def __ne__(self, other):
        if self.allowed_types == "*" or other == "*":
            return False
        return other not in self.allowed_types

class ContainsAll(dict):
    def __contains__(self, other):
        return True
    def __getitem__(self, key):
        return super().get(key, (None, {}))

def requeue_workflow_unchecked():
    """Requeues the current workflow without checking for multiple requeues"""
    currently_running = prompt_queue.currently_running
    value = next(iter(currently_running.values()))
    
    # Handle both old (5 values) and new (6 values) ComfyUI versions
    if len(value) == 6:
        (_, prompt_id, prompt, extra_data, outputs_to_execute, _) = value
    else:
        (_, prompt_id, prompt, extra_data, outputs_to_execute) = value
    
    #Ensure batch_managers are marked stale
    prompt = prompt.copy()
    for uid in prompt:
        if prompt[uid]['class_type'] == 'VHS_BatchManager':
            prompt[uid]['inputs']['requeue'] = prompt[uid]['inputs'].get('requeue',0)+1

    #execution.py has guards for concurrency, but server doesn't.
    #TODO: Check that this won't be an issue
    number = -server.PromptServer.instance.number
    server.PromptServer.instance.number += 1
    prompt_id = str(server.uuid.uuid4())
    # Put back with 6 elements to match what ComfyUI expects
    sensitive = value[5] if len(value) > 5 else {}
    prompt_queue.put((number, prompt_id, prompt, extra_data, outputs_to_execute, sensitive))

def requeue_workflow(requeue_required=(-1,True)):
    assert(len(prompt_queue.currently_running) == 1)
    global requeue_guard
    
    value = next(iter(prompt_queue.currently_running.values()))
    
    # Handle both old (5 values) and new (6 values) ComfyUI versions
    if len(value) == 6:
        (run_number, _, prompt, extra_data, outputs_to_execute, _) = value
    else:
        (run_number, _, prompt, extra_data, outputs_to_execute) = value
    
    if requeue_guard[0] != run_number:
        #Calculate a count of how many outputs are managed by a batch manager
        managed_outputs=0
        for bm_uid in prompt:
            if prompt[bm_uid]['class_type'] == 'VHS_BatchManager':
                for output_uid in prompt:
                    if prompt[output_uid]['class_type'] in ["VHS_VideoCombine", "Lyonir_SaveVideo"]:
                        for inp in prompt[output_uid]['inputs'].values():
                            if inp == [bm_uid, 0]:
                                managed_outputs+=1
        requeue_guard = [run_number, 0, managed_outputs, {}]
    requeue_guard[1] = requeue_guard[1]+1
    requeue_guard[3][requeue_required[0]] = requeue_required[1]
    if requeue_guard[1] == requeue_guard[2] and max(requeue_guard[3].values()):
        requeue_workflow_unchecked()

def merge_filter_args(args, ftype="-vf"):
    #TODO This doesn't account for filter_complex
    #Will likely need to convert all filters to filter complex in the future
    #But that requires source/output deduplication
    try:
        start_index = args.index(ftype)+1
        index = start_index
        while True:
            index = args.index(ftype, index)
            args[start_index] += ',' + args[index+1]
            args.pop(index)
            args.pop(index)
    except ValueError:
        pass

def cached(duration):
    def dec(f):
        cached_ret = None
        cache_time = 0
        def cached_func():
            nonlocal cache_time, cached_ret
            if time.time() > cache_time + duration or cached_ret is None:
                cache_time = time.time()
                cached_ret = f()
            return cached_ret
        return cached_func
    return dec
imageOrLatent = MultiInput("IMAGE", ["IMAGE", "LATENT"])
floatOrInt = MultiInput("FLOAT", ["FLOAT", "INT"])
