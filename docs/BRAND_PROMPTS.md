# Brand prompts (video, logo, backgrounds)

Ready-to-paste prompts for a generative video/image tool (written for Higgsfield; they work elsewhere too).

## Which Higgsfield model for what
Checked against the model catalogue of the connected account on 2026-11-10 (plan "ultra", 10 credits left). Models
marked *unlimited* in that catalogue are listed first - use them so the few credits are not the limit.

| Asset | Model (id) | Settings |
|---|---|---|
| Logo marks | Nano Banana Pro (`nano_banana_pro`, unlimited) | aspect 1:1, resolution 2k, 4 variations per direction |
| Wordmark "VAELON" | GPT Image 2 (`gpt_image_2`, unlimited) | aspect 3:2, resolution 2k, quality high (best at lettering) |
| Hero still, section backgrounds | Nano Banana Pro (`nano_banana_pro`) | aspect 16:9 (hero also 21:9), resolution 4k |
| Hero still, alternative look | Cinema Studio Image 2.5 (`cinematic_studio_2_5`) | aspect 21:9 or 16:9, resolution 4k (uses credits) |
| Video shots | Seedance 2.0 (`seedance_2_0`, unlimited) | mode std, 1080p, 16:9, 5-6 s per shot, genre epic, audio off |
| Video shots, top quality | Cinema Studio Video 3.0 (`cinematic_studio_3_0`) | 1080p, 16:9, 4-6 s, genre epic or noir (uses credits) |
| Seamless background loop | Seedance 2.0 (`seedance_2_0`) | start image = end image = the hero still, 6-8 s, audio off |

**Order that keeps everything consistent**
1. Make the hero still first and pick ONE you love. It defines the colour and the particle look.
2. Make the logo marks and the wordmark.
3. For every video shot, first generate a still of that shot with Nano Banana Pro using the hero still as an image
   reference, then animate it with Seedance 2.0 using that still as the **start image**. Text-only video drifts in
   style from shot to shot; image-to-video does not.
4. Cut the shots together and add the on-screen lines and sound in an editor.

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
