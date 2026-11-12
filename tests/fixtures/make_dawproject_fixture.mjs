// Writes tests/fixtures/dawproject-project.xml and dawproject-metadata.xml (EXP.3): what dawproject.js
// writes for the notation fixture's song (tests/fixtures/notation-project.json: an F major melody at
// 96 bpm and its chords) with four drum hits, the original and tuned takes, the separated music and a
// muted band. tests/test_dawproject.py validates both against the DAWproject 1.0 schema and reads the
// tracks back; tests/dawproject.test.mjs checks projectXml and metadataXml still write them.
// Run from the repository root: node tests/fixtures/make_dawproject_fixture.mjs
import { readFile, writeFile } from "node:fs/promises";
import { metadataXml, projectXml } from "../../dawproject.js";

export const FIXTURE_AUDIO = {
  original: { seconds: 10.5 },
  tuned: { seconds: 10.5 },
  accompaniment: { seconds: 10.5 },
  band: { seconds: 12, gain: 0.8, muted: true },
};
// As dawProject sets them: the tuned take plays, the original is muted.
export const FIXTURE_MUTED = { original: true, tuned: false, accompaniment: false, band: true };

export async function fixtureSong() {
  const { title, key, project } = JSON.parse(await readFile(new URL("./notation-project.json", import.meta.url), "utf8"));
  const beat = 60 / project.bpm;
  const drums = [["kick", 0], ["hat", 0.5], ["snare", 1], ["hat", 1.5]].map(([k, b]) => ({ k, t: Math.round(b * beat * 1000) / 1000 }));
  const audio = Object.fromEntries(Object.entries(FIXTURE_AUDIO).map(([slot, a]) => [slot, { ...a, muted: FIXTURE_MUTED[slot] }]));
  return { title, key, project: { ...project, drums }, audio };
}

if (import.meta.url === `file://${process.argv[1]}`) {
  const { title, key, project, audio } = await fixtureSong();
  await writeFile(new URL("./dawproject-project.xml", import.meta.url), projectXml(project, { audio, rate: 44100 }));
  await writeFile(new URL("./dawproject-metadata.xml", import.meta.url), metadataXml({ title, key }));
  console.log("wrote dawproject-project.xml and dawproject-metadata.xml");
}
