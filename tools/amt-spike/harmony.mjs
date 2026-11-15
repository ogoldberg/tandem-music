// AMT.0 spike: harmony.js's own accompaniment for a project read from stdin, as JSON on stdout.
// Usage: node tools/amt-spike/harmony.mjs chords|bass < project.json
import { generateHarmony } from "../../harmony.js";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const project = JSON.parse(Buffer.concat(chunks).toString("utf8"));
const style = process.argv[2] ?? "chords";
process.stdout.write(JSON.stringify(generateHarmony(project, { style })));
