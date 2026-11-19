# Brief for Claude chat: make the Vaelon brand assets with Higgsfield

Paste everything below this line into **Claude chat** (not Claude Code) with the Higgsfield connector switched on.
Higgsfield's free-trial unlimited generations work in Claude chat, Claude Cowork and ChatGPT; from Claude Code only
paid credits can be used (an image is 0.5-2 credits, one 5-second video shot is about 22 credits).

---


You have the Higgsfield connector. Make the brand assets for my app **Vaelon** (a private, open-source AI
assistant for the desktop). Use my **free-trial unlimited generations for every request** (`use_unlim: true`) and
never spend credits: if a request cannot run on the unlimited allowance, stop and tell me instead of charging.
Unlimited requests make one result each, so for several variants submit several requests in one batch.

Work in this order and show me the results after each step:

1. **Hero background** - 4 variants. Model `nano_banana_pro`, aspect 16:9, resolution 4k (2k if 4k is not covered),
   prompt "Hero" below. Show me all four and ask me which one I choose. Do not continue before I answer.
2. **Logo marks** - directions A to F below, 2 variants each (12 images). Model `nano_banana_pro`, aspect 1:1, 2k.
3. **Wordmark "VAELON"** - 3 variants. Model `gpt_image_2_6`, aspect 3:2, 2k, quality high, prompt "Wordmark" below.
4. **Shot stills** - for each of the 7 video shots below, one still. Model `nano_banana_pro`, aspect 16:9, 2k, with
   the hero I chose as an image reference so that colour and particles match.
5. **Video shots** - animate each still. Model `seedance_2_0` (mode std, 1080p, 16:9, 5 seconds, genre epic,
   generate_audio false), the still as `start_image`, the shot text as the prompt.
6. **Background loop** - one clip, `seedance_2_0`, 8 seconds, the chosen hero as both `start_image` and
   `end_image`, prompt "Looping motion version" below.
7. **Section backgrounds and social card** - the five section prompts and the Open Graph card below,
   `nano_banana_pro`, 16:9, 2k.

At the end give me one list of everything with its link, grouped by step, and tell me which results you would pick.

## The look (keep it identical in every asset)
- **Subject:** a living swarm of thousands of tiny glowing particles that moves like a murmuration of starlings.
  It has no face and no fixed body; it folds into ribbons, vortices and rings.
- **Colour:** deep black void (#050304). Particles ember orange (#FF7A1F) with hot gold cores; rare, sudden
  flashes of blood red (#FF1F2D).
- **Feel:** calm, intelligent, private, slightly dangerous. Cinematic, minimal, no clutter.
- **Never:** robots, humanoid faces, helmets, a red-eyed android, comic-book armour, circuit-board clichés, stock
  "AI brain" imagery, any existing film character.

---

## 1. Launch video (20-30 s, 16:9, also cut 9:16)

**Master prompt**
> Cinematic product film, pitch-black void. Thousands of tiny ember-orange glowing particles drift like a
> murmuration of starlings, folding into ribbons and slow vortices, gold-hot cores, soft volumetric glow, shallow
> depth of field, fine dust in the air, anamorphic lens, 35mm film grain, high contrast, deep blacks. The swarm is
> alive and intelligent but has no face and no body. Slow, confident camera. Mood: calm power, private, premium.
> Colour palette strictly black, ember orange, gold, with one brief flash of blood red. No text, no people, no
> robots, no logos.

**Shots** (generate each as its own clip, 4-6 s, then cut together)
1. *Awakening.* Total darkness. One spark appears, then hundreds, then thousands pour in from the edges and
   gather into a slowly breathing cloud. Camera: slow push-in.
2. *Listening.* The cloud flattens into a wide rippling dish, the ripples pulsing like a voice waveform.
   Camera: low angle, slow orbit left.
3. *Thinking.* The swarm tightens into a tilted spinning vortex; single particles fire white-hot like neurons.
   Camera: crash zoom into the core.
4. *Many tasks at once.* The swarm tears itself into three separate clusters - amber, cyan, violet - each
   spinning its own shape, thin trails of particles still flowing between them. Camera: wide, slow pull-back.
5. *Seeing.* The clusters merge; the swarm forms a ring like an iris around a faint reflection of a desktop
   screen, particles scanning across it. Camera: straight on, very slow dolly in.
6. *The glitch.* For half a second the whole swarm snaps blood red, tears horizontally like a corrupted frame,
   then recovers to calm orange. Camera: locked off, one hard shake.
7. *Signature.* The swarm collapses into a small dense glowing orb floating in the corner of a dark desk at
   night, a laptop softly lit beside it. Camera: slow push-in, then hold. (Leave clean space for the wordmark.)

**On-screen lines** (add in the editor, not in the generator)
`It listens.` / `It thinks.` / `It does ten things at once.` / `It sees what you see.` /
`And it never leaves your machine.` / `Vaelon - your private AI. Free and open source.`

**Sound:** deep sub pulse, granular whispers that follow the swarm's motion, one sharp digital tear on the glitch,
silence before the final line.

**Short vertical cut (9:16, 8-10 s):** shots 1, 4, 6, 7.

---

## 2. Logo (make several, pick one family)

Use this base for every direction:
> Minimal vector logo mark on a pure black background, flat, geometric, perfectly centred, generous empty space,
> ember orange (#FF7A1F) with a subtle gold-to-orange gradient, crisp edges, no text, no mock-up, no 3D render, no
> photo, no shadow, suitable as an app icon at 32 px. Award-winning brand identity, Swiss design.

**Directions** (append one line to the base)
- **A - Murmuration ring:** "A circle made of hundreds of small dots that thin out and break apart on one side,
  like a flock turning in the sky."
- **B - Ember core:** "A small solid glowing dot at the centre with three incomplete orbit arcs of different
  radius around it, each arc made of dots."
- **C - The iris:** "An abstract eye built from two opposed crescent swarms of dots with an empty round centre -
  it reads as an eye and as a vortex."
- **D - Monogram:** "The capital letter **V** formed only by a flowing ribbon of dots that
  bends like a murmuration, one dot blood red."
- **E - Split:** "One dense cluster of dots splitting into three smaller clusters connected by thin trails -
  amber, cyan and violet on black."
- **F - Glitch mark:** "A solid ember-orange circle cut by two thin horizontal slices shifted sideways, the
  shifted slices blood red - a clean glitch."

**Wordmark** (separate generation, or set it by hand)
> Wordmark "Vaelon" in wide-tracked uppercase geometric sans-serif, heavy weight, ember orange on black, the
> letters slightly eroded into fine particles on the right edge, flat vector, no effects.

**Deliverables to ask for:** square icon (1024 px), horizontal lockup (mark + wordmark), single-colour white
version, single-colour black version, favicon at 32 px.

---

## 3. Website and app backgrounds

**Hero (16:9, 4K, calm area in the centre for the headline)**
> Ultra-wide dark website hero background, pure black void (#050304) with a huge murmuration of ember-orange
> glowing particles sweeping from the lower left to the upper right, dense and bright at the edges, thin and almost
> empty in the centre so a headline stays readable, soft volumetric glow, faint warm haze near the bottom, subtle
> film grain, cinematic depth of field, no text, no objects, no people. 4K, 16:9.

**Looping motion version (6-8 s, seamless)**
> Same scene as a seamless loop: the swarm drifts and folds very slowly, never leaving the frame, constant
> brightness, locked camera, start and end frames identical.

**Section backgrounds (generate as a set, same palette)**
- *Privacy:* "the swarm contained inside a faint glass sphere on a dark desk, nothing escaping it."
- *Many tasks:* "three separate particle clusters - amber, cyan, violet - on black, thin trails between them."
- *Voice:* "particles arranged as a horizontal waveform dissolving into dust at both ends."
- *Sees your screen:* "a ring of particles like an iris around a soft glowing rectangle."
- *Footer / texture:* "sparse ember dust on black, very low contrast, tileable."

**Open Graph / social card (1200 x 630):** the hero with the swarm pushed to the right half, left half empty
black for the logo and one line.

---

## Notes
- Generate at the highest quality the plan allows and keep the seeds of the versions you like - consistency
  between video, logo and site matters more than any single image.
- Check the terms of the tool for commercial use of the outputs before publishing.
- The logo generator gives a direction, not a final file: have the chosen mark redrawn as a clean vector (SVG).
