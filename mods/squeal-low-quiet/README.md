# Optional: quieter tire squeal

The tire squeal that plays on launch wheelspin, while drifting through corners
and during long slides is a piercing 3.5–4.4 kHz trill. This patch plays it
two octaves lower (about 0.9–1.1 kHz) at less than half the volume (5 instead
of 12). Nothing else changes.

## Applying

Apply [`squeal-low-quiet.ips`](squeal-low-quiet.ips) **after** the English
translation patch. It also works on its own on the original Japanese ROM. It
only changes bytes `0x8EDF–0x8F59`, which the translation doesn't touch, so the
order doesn't matter in practice.

## How it works

The squeal isn't a sound effect. It's three short music-sequencer tracks in
bank 2 (tracks 9, 10 and 11, via the table at `$444D`). They play on channel 1
and the game restarts them every 7 frames while the tires are slipping:

| Track | Plays during | Original notes |
|---|---|---|
| 9 | Wheelspin at launch | `45/47` trill (3.5–4.0 kHz) |
| 10 | Cornering drift | `48/47/46` trill (3.8–4.2 kHz) |
| 11 | Long slide | sweep, then `48/49` trill (up to 4.4 kHz) |

The patch moves every note down 24 semitones and changes the `F6 C0` volume
command to `F6 50`. The streams keep their length, so they're rewritten in
place.

To rebuild:

```bash
python3 -I mods/squeal-low-quiet/build_squeal_mod.py "<rom.gb>" mods/squeal-low-quiet
```
