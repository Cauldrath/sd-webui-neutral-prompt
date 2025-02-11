import torch
from modules import scripts, processing, prompt_parser, script_callbacks, sd_samplers_kdiffusion, shared
import gradio as gr


is_enabled = False
neutral_prompt = ''
neutral_cond_scale = 1.0
cfg_rescale = 0


def combine_denoise_hijack(self, x_out, conds_list, uncond, cond_scale):
    global is_enabled, neutral_cond_scale, cfg_rescale
    if not is_enabled:
        return original_combine_denoise(self, x_out, conds_list, uncond, cond_scale)

    x_neutral = x_out[conds_list[0][0][0]]
    x_uncond = x_out[-uncond.shape[0]:]
    denoised = torch.clone(x_uncond)

    del conds_list[0][0]

    x_pos_std = 0

    for i, conds in enumerate(conds_list):
        for cond_index, weight in conds:
            x_pos = x_out[cond_index]
            x_pos_std += torch.std(x_pos)
            x_pos_delta = x_pos - x_uncond[i]
            x_cfg = x_pos_delta + neutral_cond_scale * get_perpendicular_component(x_pos_delta, x_neutral - x_uncond[i])
            denoised[i] += x_cfg * (weight * cond_scale)

    x_cfg_std = torch.std(denoised)
    denoised *= cfg_rescale * (x_pos_std / x_cfg_std - 1) + 1

    return denoised


original_combine_denoise = getattr(sd_samplers_kdiffusion.CFGDenoiser, '__neutral_prompt_original_combine_denoise', sd_samplers_kdiffusion.CFGDenoiser.combine_denoised)
setattr(sd_samplers_kdiffusion.CFGDenoiser, '__neutral_prompt_original_combine_denoise', original_combine_denoise)
sd_samplers_kdiffusion.CFGDenoiser.combine_denoised = combine_denoise_hijack


def get_perpendicular_component(pos, neg):
    projected_neg = pos * torch.sum(neg * pos) / torch.norm(pos) ** 2
    return neg - projected_neg


def get_multicond_learned_conditioning_hijack(model, prompts, steps):
    global is_enabled, neutral_prompt
    if not is_enabled:
        return original_get_multicond_learned_conditioning(model, prompts, steps)

    res = original_get_multicond_learned_conditioning(model, prompts, steps)
    res.batch[0].insert(0, prompt_parser.ComposableScheduledPromptConditioning(
        schedules=prompt_parser.get_learned_conditioning(model, [neutral_prompt], steps)[0],
        weight=0.
    ))
    return res


original_get_multicond_learned_conditioning = getattr(prompt_parser, '__neutral_prompt_original_get_multicond_learned_conditioning', prompt_parser.get_multicond_learned_conditioning)
setattr(prompt_parser, '__neutral_prompt_original_get_multicond_learned_conditioning', original_get_multicond_learned_conditioning)
prompt_parser.get_multicond_learned_conditioning = get_multicond_learned_conditioning_hijack


def on_script_unloaded():
    prompt_parser.get_multicond_learned_conditioning = original_get_multicond_learned_conditioning
    sd_samplers_kdiffusion.CFGDenoiser.combine_denoise = original_combine_denoise


script_callbacks.on_script_unloaded(on_script_unloaded)


class NeutralPromptScript(scripts.Script):
    def title(self) -> str:
        return "Neutral Prompt"

    def show(self, is_img2img: bool):
        return scripts.AlwaysVisible

    def ui(self, is_img2img):
        with gr.Accordion(label='Neutral Prompt', open=False):
            ui_enabled = gr.Checkbox(label='Enable', value=False)
            ui_neutral_prompt = gr.Textbox(label='Neutral prompt ', show_label=False, lines=3, placeholder='Neutral prompt')
            ui_neutral_cond_scale = gr.Slider(label='Neutral CFG ', minimum=-3, maximum=0, value=-1)
            ui_cfg_rescale = gr.Slider(label='CFG Rescale ', minimum=0, maximum=1, value=0)

        return [ui_enabled, ui_neutral_prompt, ui_neutral_cond_scale, ui_cfg_rescale]

    def process(self, p: processing.StableDiffusionProcessing, ui_enabled, ui_neutral_prompt, ui_neutral_cond_scale, ui_cfg_rescale):
        global is_enabled, neutral_prompt, neutral_cond_scale, cfg_rescale
        is_enabled = ui_enabled
        neutral_prompt = ui_neutral_prompt
        neutral_cond_scale = ui_neutral_cond_scale
        cfg_rescale = ui_cfg_rescale
