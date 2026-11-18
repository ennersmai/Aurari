# PRD: Aura Avatar v2

**Owner:** Mai
**Status:** v3 draft for review, then agent execution
**Applies to:** `Aura-Core/aura-app/frontend`, the animation and voice routes in the backend, and a new `animation` table in SurrealDB
**Based on:** the WebGPU avatar blueprint, a read of `emotionToVrm.ts`, the renderer setup in `viewer.ts`, `lipSync.ts`, the voice route's provider handling and the backend `l5_animation` route. The 1,500-line viewer and the animation router were surveyed, not read in full.

**Changes in v2:** full body, not head and bust. The VRM window and everything it depends on is removed, with no fallback rig. A gesture layer with an animation library stored in SurrealDB. The asset is built by Mai from a free base. Budgets aligned with the blueprint.

---

## 1. Summary

Replace the anime VRM avatar with a stylised-realistic full-body character rendered through WebGPU, driven by a layered controller. Her face and body show three things: how she feels, what her mind is doing, and the physical actions she describes in her replies.

Art direction is an original design in the stylised-realistic range the blueprint describes: realistic proportions and eyes, clean luminous skin, pulled-back hair, poised and restrained movement. Reference games inform the brief. The model, its name and its marketing must not reproduce an existing character.

---

## 2. Findings in the current code

| # | Finding | Where |
|---|---|---|
| A1 | The 27D emotion vector is reduced to five VRM presets by a weighted sum, then eased toward the target. | `components/vrm-engine/features/vrmViewer/emotionToVrm.ts` |
| A2 | The same table maps emotions onto the mouth shapes `aa`, `ih`, `ou`, `ee`, `oh`, which are the shapes speech needs. Emotion and speech compete for the mouth. | `emotionToVrm.ts` |
| A3 | Lip sync reads audio volume only. There are no visemes. | `features/lipSync/lipSync.ts` |
| A4 | Body animation is chosen per turn by a model call from a hard-coded list of clips (dance, spin, peace sign, squat). | `api/routes/l5_animation.py` |
| A5 | The weight table references `amusement` and `loneliness`, which are not among the 27 dimensions. | `emotionToVrm.ts` |
| A6 | Pixel ratio is set to the device's full value. | `viewer.ts` |
| A7 | The renderer tries WebGPU through a deep import path inside three 0.169 and falls back to WebGL. | `viewer.ts` |
| A8 | Her resting emotional state is a plateau of nine dimensions near 0.7 (see `AURA_EMOTION_PRD.md`). Any face driven by the raw state would hold one expression. | emotion engine |
| A9 | Three voice providers are already wired: Edge, Qwen3-TTS and a local Fish Audio model. | `api/routes/voice.py`, `config.py` |

---

## 3. Goals and non-goals

### Goals

1. A full-body character with a facial rig on the ARKit standard, built from a free base and finished by Mai.
2. A layered controller for face and body with clear ownership of every channel.
3. A face that reflects cognitive state from real pipeline events.
4. A gesture layer that performs the actions she writes, from an animation library she can grow.
5. Visemes when voice output is on.
6. 60 fps on the reference desktop (GTX 1060) and on a mid-range phone.
7. The VRM avatar and all of its dependencies removed.

### Non-goals (this version)

- Locomotion and walking around a scene.
- Voice input, interruption and full-duplex conversation.
- A character creator or multiple selectable characters.
- Photorealism.

---

## 4. Removing the VRM avatar

Done first, in one change, so the two systems never coexist.

| Remove | Notes |
|---|---|
| `frontend/src/components/vrm-engine/` | whole directory |
| `frontend/src/components/VrmModelSelector.tsx` | |
| `frontend/src/components/AvatarCanvas.tsx`, `AuraAvatar.tsx`, `FloatingAvatarWindow.tsx` | replaced by one `AvatarStage` component |
| `frontend/src/services/animationRouterInstance.ts` | |
| `frontend/src/services/avatarAudioBridge.ts` | rewritten for the new speech layer |
| Avatar references in `pages/chat.tsx` and `components/chat/ChatMessage.tsx` | including the pursuit-tag regex if the behaviour PRD has not already removed it |
| `frontend/public/vrm-assets/` | models and `.vrma` clips |
| `vrm-animations-temp/` at the repository root | |
| `@pixiv/three-vrm` in `package.json` | |
| `src/aura/api/routes/l5_animation.py` and its registration in `main.py` | |

`SpiralAvatar.tsx` is plain three.js with no VRM dependency. It stays as what the app shows while the new avatar is loading or if it fails to load.

After this change the app must build and run with the spiral in place of the avatar.

---

## 5. The asset

Built by Mai. The pipeline must be scripted so every re-export goes through the same checks.

### 5.1 Base: the MetaHuman Mai already made

Mai has a finished MetaHuman and stopped at facial animation. That wall does not exist on this route: **no facial animation is authored by hand, and no animation pack is needed.** The runtime controller in section 7 animates the face from data. The asset only has to contain the face shapes as static targets.

MetaHuman faces are driven by a rig description stored in a `.dna` file. The steps, all scripted:

1. **Get the character out of Unreal.** Export the MetaHuman's `.dna` file and its head and body meshes and textures at a mid level of detail. If the project files still exist, this may not need Unreal to run at all.
2. **Load it in Blender with the free Character DNA add-on,** which reads the `.dna` and evaluates the face rig the way Unreal does.
3. **Bake the face shapes by script.** For each of the ARKit shape names, the script sets the rig controls to the pose Unreal's own ARKit mapping uses, and saves the resulting mesh as a shape key. Then the same for the 15 visemes. The bake is known to be approximate for a few shapes (mouth close especially), which are touched up by eye afterwards.
4. **Export a `.glb`** and run the build script in 5.3.

Blender runs these steps headless from the command line (`blender --background --python bake_face.py`). Nobody has to learn its interface. A coding agent writes and debugs the script.

What this route does not carry over:

- **Hair.** MetaHuman strand hair does not export. Use the card or mesh version of the hairstyle if the character has one, or a separate hair-card asset. A pulled-back style is the easy case.
- **The skin shader.** Unreal's skin material stays behind. The textures come across, and the look is rebuilt in section 6.
- **Clothing** made of Unreal-only materials needs its textures baked.

Licence: MetaHuman is free below a revenue threshold and permitted in other engines. Read the current terms before shipping.

**Milestone V1 starts with a proof:** one page that loads the exported head and shows a slider per face shape. When every slider moves the face correctly, the wall is gone and everything after it is code.

### 5.1a Fallback base

If the MetaHuman files are lost and cannot be rebuilt, MPFB (MakeHuman for Blender) is the free fallback: full body, rig, ARKit shapes and visemes from asset packs, CC0 base mesh. It needs more artistic work to look good. It is also a fine development placeholder while the MetaHuman export is being sorted out.

### 5.2 Requirements

| Item | Requirement |
|---|---|
| Skeleton | standard humanoid bone names, so retargeted clips apply without per-clip fixes |
| Face shapes | the ARKit set and the 15 visemes at authoring time, on the head mesh only |
| Mesh split | head as its own mesh, so body vertices carry no shape-key data |
| Triangles | 25,000 to 35,000 for mobile, up to 50,000 for desktop, whole character |
| Draw calls | 8 to 10 at most, using merged meshes and 2 to 3 texture atlases |
| Eyes | separate eyeballs with a cornea shell |
| Hair | pulled back, cards or sculpted mesh, minimal transparency |
| Textures | up to 2K, warm subsurface tones and ambient occlusion baked into colour |
| Delivery size | 5 to 15 MB after compression |

### 5.3 Build script

`frontend/scripts/build-avatar`, using `gltf-transform`:

1. deduplicate, weld, prune
2. **prune shape keys:** remove every face shape that no mapping table in section 7 or 9 references. Authoring keeps the full set, shipping keeps the roughly 25 to 30 in use.
3. mesh compression
4. textures to KTX2
5. a report of triangles, draw calls, shape count, texture memory and file size. The build fails when any budget in 5.2 is exceeded.

### 5.4 Developing before the final asset exists

Controller work does not wait for the export. Any head with the ARKit shape names works as a placeholder (an untouched MPFB export is the simplest). The controller is written against bone and shape names, so the real character is a file swap.

---

## 6. Rendering

- Upgrade three to a current release and use its WebGPU renderer with the built-in fallback to WebGL 2. Import paths and material API must come from the documentation of the version chosen.
- Cap pixel ratio at 1.5 on mobile and 2.0 on desktop.
- No real-time shadow maps. Baked ambient occlusion and a soft baked shadow plane.
- Skin: baked warm tones plus a light sheen and rim term. No multi-pass skin shader.
- Eyes: iris layer plus a glossy cornea shell reflecting a small studio environment map.
- **Framing modes:** portrait (head and shoulders), half body, full body. The app picks by panel size, and the owner can switch. Portrait uses a higher texture level for the face.
- **Governor:** when frame time exceeds budget for one second, step down pixel ratio, then environment map resolution, then hair detail. Step back up when there is headroom.

---

## 7. The controller

A new module `frontend/src/avatar/controller/`. Six layers each produce partial values for shapes and bones every frame. A fixed ownership table decides which layer wins each channel.

| Layer | Timescale | Driven by | Owns |
|---|---|---|---|
| 1. Idle life | continuous | procedural: breathing, weight shift, spine and neck noise, hand settle | whole body base pose |
| 2. Affect | seconds | emotional deviation from baseline | brows, lids, cheeks, mouth corners at rest, posture openness |
| 3. Cognitive state | hundreds of ms to seconds | pipeline events (section 8) | gaze, head tilt, brow modifiers |
| 4. Events | 200 to 600 ms pulses | surprise, amusement, a nod | short additive bursts |
| 5. Speech | per frame while speaking | visemes | jaw and mouth-shape channels |
| 6. Gesture | 1 to 5 s clips | her written actions and context (section 9) | arms, hands, torso and head through bone masks |

Rules:

- While speech is active, affect on the lower face is scaled to 30%.
- A gesture clip never writes face shapes. Faces come from layers 2 to 5.
- A gesture blends in and out over 200 to 300 ms and releases its bones back to idle life.
- Look-at (eyes, then head, then a little chest) is part of layer 3 and continues under a gesture unless the clip's mask includes the head.
- Blink is its own small system, linked to gaze shifts and pauses in speech.

### 7.1 Affect: from 27 dimensions to face and posture

1. **Use the deviation.** The input is her state minus her baseline, which the emotion engine provides directly. At rest the face is neutral.
2. **Dominant few.** Keep the top two or three dimensions. A newcomer must beat the current third place by a margin for 300 ms before replacing it.
3. **Action units.** A JSON table maps each dimension to facial action units, and a second table maps action units to ARKit shapes.
4. **Zones.** Inward dimensions (curiosity, confusion, doubt, certainty, fascination, boredom) weight the upper face. Social ones (joy, love, gratitude, empathy, compassion) weight the lower face.
5. **Asymmetry.** 5 to 10% left and right offset, fixed per expression.
6. **Eyes lead.** Upper-face channels start 150 to 250 ms before lower-face ones. Affect only, never visemes.
7. **Posture.** Valence and arousal from her mood shift the idle pose slightly: chest and chin up or down, shoulders open or closed, breathing rate.

Tables are data. A development-only panel edits them live.

---

## 8. Showing what she is doing

The avatar subscribes to a reduced form of the pipeline trace stream. No model call chooses these states.

| Cognitive state | Triggered by | What she does |
|---|---|---|
| Attending | the user is typing, or a message just arrived | gaze to camera, slight lean in, a small nod when the message lands |
| Recalling | the Recall Engine is running | gaze drifts up and aside, lids narrow |
| Thinking | the reasoning layer is running | gaze averted down, brows drawn slightly, slower blinks |
| Unsure | the context packet set `abstain`, or confidence is low | small head tilt, one brow raised |
| Found it | recall returned a strong match | brief brow lift, gaze back to camera |
| Surprised | a prediction settled with large error | an event pulse: brows up, lids wide |
| Working | a delegated task is running | relaxed, glancing aside at intervals |
| Curious | an investigation is running in idle time | head tilted, eyes moving as if reading |
| Resting | dreaming or sleeping | eyes closed or half closed, slow breathing |

---

## 9. The gesture layer and the animation library

### 9.1 The library

A new table `animation` in SurrealDB:

| Field | Meaning |
|---|---|
| `name` | short identifier |
| `file` | path of the clip (an animation-only `.glb`) |
| `description` | what the motion is, in plain words ("leans forward with interest, hands together") |
| `phrases` | example ways she might write it ("I lean closer", "leaning in") |
| `embedding` | vector of description and phrases |
| `kind` | `gesture`, `posture`, `reaction`, `emote` |
| `mask` | `arms`, `upper_body`, `head`, `full_body` |
| `duration_ms`, `loop` | |
| `intensity` | 0 to 1 |
| `affect_fit` | which emotional directions it suits |
| `source`, `licence` | where the clip came from and its terms |
| `plays`, `last_played` | usage |

A second table `animation_gap` records actions she wrote that matched nothing, with a count. That list tells Mai which clips to make next.

Clips are retargeted to the avatar's skeleton offline in Blender and exported animation-only. Sources: recorded with a webcam motion-capture tool, a licensed mocap pack, or free libraries whose terms allow embedding in a product. Every clip's terms are recorded in the `licence` field.

An admin page lists the library, plays any clip on the avatar and edits descriptions and phrases.

### 9.2 Where gestures come from

**Path A, written actions.** As her reply streams, the backend detects completed action spans (text between asterisks). For each span:

1. Embed the span and search the library by vector similarity.
2. Above a high threshold: send the top match to the avatar at once.
3. In a middle band: ask the small fast model to choose among the top five or answer none. This runs in the background and never delays the text.
4. Below the low threshold: no gesture. Record the span in `animation_gap`.

**Path B, context.** After a reply with no written action, the small fast model may be asked for one gesture. It receives the last user message, the reply, her dominant emotions and cognitive state, and the ten library entries most similar to the reply, and returns one name or none. This is rate limited (at most once every few turns) and can be switched off.

Both paths deliver an `avatar_gesture` event. The client plays it if the avatar is idle enough, otherwise drops it. Nothing queues for more than two seconds.

### 9.3 Rules

- At most one gesture every four seconds.
- A gesture never plays while the user is typing a reply to something else.
- An owner setting decides whether action text that was performed stays visible in chat or is hidden.
- The small model is one of the existing layer models, selectable in the tier settings.

---

## 10. Speech

Only when voice output is on. In text mode the mouth belongs to affect.

### 10.1 Providers

Wrap the three existing providers, and any new one, behind one interface that declares what each can do:

```python
class TTSProvider:
    name: str
    streaming: bool
    timing: Literal["none", "word", "phoneme", "viseme"]
    emotion_control: bool
    async def synthesize(self, text: str, voice: str, style: StyleHint) -> AsyncIterator[AudioChunk]
```

The reference machine is already loaded, so local speech models are not a default. The provider to add first is Azure Speech on its free tier: the same family of voices Edge uses, with speaking styles for emotion and, to be confirmed against its documentation, viseme timing events. Edge stays as the fallback.

### 10.2 Lip sync

Chosen by the provider's `timing`:

1. `viseme` or `phoneme`: map directly to the 15 viseme shapes.
2. `word` or `none`: estimate visemes in the browser from the audio with a small spectral classifier.
3. The current volume-based method remains only as a last resort.

Smooth transitions over 40 to 60 ms and reduce amplitude at high speaking rates.

---

## 11. Protocol

Websocket messages on the existing connection:

`avatar_state`, on change and at most 10 times a second:

```json
{
  "deviation": { "joy": 0.22, "curiosity": 0.31 },
  "mood": { "valence": 0.2, "arousal": 0.5 },
  "cognitive_state": "recalling",
  "events": [{ "type": "surprise", "strength": 0.7 }],
  "speaking": false,
  "gaze_target": "camera"
}
```

`avatar_gesture`, when a gesture is chosen:

```json
{ "animation": "lean_in", "file": "/avatar/clips/lean_in.glb", "mask": "upper_body", "source": "written_action" }
```

All face mapping lives in the client. The gesture choice lives in the backend, because it needs the database.

---

## 12. Testing

| # | Test | Pass condition |
|---|---|---|
| T1 | VRM removal | no import of `three-vrm` or `vrm-engine` remains, the app builds and runs with the spiral |
| T2 | Channel ownership | on every frame of a recorded session, no channel is written by two layers outside the rules in section 7 |
| T3 | Hysteresis | two near-equal emotions alternating produce at most one expression change per second |
| T4 | Neutral at rest | zero deviation produces the neutral face and pose |
| T5 | Speech priority | with speech active, lower-face affect is at 30% |
| T6 | Event decay | every event pulse returns to zero within 600 ms |
| T7 | Cognitive states | a replayed trace of one turn produces attending, recalling, thinking, attending in order |
| T8 | Written action, strong match | "*leans closer*" plays the lean clip with no model call |
| T9 | Written action, no match | nothing plays, a row appears in `animation_gap` |
| T10 | Gesture never blocks text | time to first text token is unchanged with the gesture layer on |
| T11 | Gesture and face | a playing gesture changes no face shape |
| T12 | Rate limit | five actions in one reply produce at most the allowed number of gestures |
| T13 | Asset budgets | the build fails when any limit in 5.2 is exceeded |
| T14 | Shape pruning | the shipped file contains only shapes referenced by the tables |
| T15 | Performance | median frame time under 16.6 ms on the reference desktop in full-body framing, governor engages and recovers under load |
| T16 | WebGL fallback | the scene renders with WebGPU disabled |
| T17 | Reference images | 12 canonical states rendered and compared to approved images |

---

## 13. Milestones

| Milestone | Scope | Tests |
|---|---|---|
| V0 | Remove the VRM avatar (section 4). Spiral in its place. | T1 |
| V1 | Export proof: bake script, exported head, slider page (5.1). `AvatarStage` with a placeholder. three upgraded, WebGPU with fallback, pixel ratio cap, framing modes. Build script with budgets and shape pruning. | T13, T14, T16 |
| V2 | Controller skeleton, six layers, ownership table. Idle life, look-at and blink. | T2, T6 |
| V3 | Affect layer on deviation, with tables, zones, asymmetry, eye lead, posture. Tuning panel. | T3, T4, T17 |
| V4 | Cognitive state layer from trace events. `avatar_state` protocol. | T7 |
| V5 | `animation` table, admin page, written-action path with vector match and gap logging | T8, T9, T11, T12 |
| V6 | Small-model paths (middle band and context gestures) | T10 |
| V7 | Speech: provider interface, viseme lip sync | T5 |
| V8 | Final asset from Mai, shading pass, governor, mobile level of detail | T15, T17 re-approved |

V3 needs the emotion engine to expose deviation (emotion PRD milestone E3). Until then V3 can run on `state - configured_baseline` computed in the client, with the caveat in finding A8.

---

## 14. Rules for the coding agent

1. Do V0 first and alone. Do not start V1 in the same change.
2. Write the controller against bone and shape names and the ownership table. No asset-specific code.
3. All mapping weights live in JSON, not in TypeScript.
4. No model call on the path from a user message to the first frame of her response. Model calls for gestures are background only.
5. Take renderer and material API details from the documentation of the three version installed.
6. The avatar must never block the chat. If it fails to load, the spiral shows and the app works.
7. No model, texture or clip enters the repository without an entry in the licences file or the `licence` field.

---

## 15. Open items for Mai

1. Do the MetaHuman project files still exist (the `.dna`, meshes and textures)? That decides whether step 1 of 5.1 is a file copy or needs Unreal running again.
2. Outfit and hair direction, which drive most of the triangle and draw-call budget.
3. How many clips for the first library. A useful start is about 15: lean in, lean back, nod, head shake, shrug, small wave, hand to chin, arms crossed, open palms, point, glance away, laugh, sigh, stretch, tilt.
4. Should performed action text be hidden or kept visible by default?
5. Which voice provider to treat as the default once candidates are tested.
