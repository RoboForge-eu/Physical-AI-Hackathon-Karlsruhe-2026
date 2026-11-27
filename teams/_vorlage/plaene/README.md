# Your own recording plans

A recording plan says for every round **where** an object should stand. Example: `plaene/elektrodose.json` in the
program folder (50 rounds, a junction box at changing spots in the half ring in front of the arm).

Create your own plan: copy the example file here, change `id` (same as the file name without `.json`),
then adapt `name`, `datensatz` (dataset), `objekt` (object), `bauteile` (parts) and `geometrie` (size in cm, radii
around the arm base). The app picks the plan up automatically; it then appears in control mode for recording.

Tip for your coding agent: "Write a recording plan for <object>, <n> rounds, radius 16-38 cm."
