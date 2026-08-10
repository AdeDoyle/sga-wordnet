# sga-wordnet

A wordnet for Old Irish (ISO 639-3: `sga`), built with the [extend
method](https://globalwordnet.github.io/gwadoc/) from the [Open English
Wordnet](https://github.com/globalwordnet/english-wordnet).

## Method

1. Start from the Old Irish [Universal
   Dependencies](https://universaldependencies.org/) corpus developed by
   Adrian Doyle, which pairs Old Irish sentences with English translations.
2. Word-align the Old Irish and English sentences to find candidate
   translation pairs for each Old Irish lemma.
3. Run word sense disambiguation on the English side of each aligned pair to
   identify the Open English Wordnet sense it expresses.
4. Import that English Wordnet sense, replacing its English lemma with the
   corresponding Old Irish lemma from the corpus, to create the Old Irish
   entry.

The resulting wordnet is produced in the [Global WordNet Association
LMF](https://globalwordnet.github.io/schemas/) format so that it is
compatible with, and editable in, the [EWE Wordnet
Editor](https://github.com/jmccrae/ewe).

## Repository layout

- `data/` — working/derived data: the UD corpus in CoNLL-U format,
  alignments (`.align`), Old Irish/English sentence pairs (`.en-ga`),
  sense-disambiguation output (`.senses`, `.results_AD.xlsx`), the Teanga
  corpus (`.teanga.yaml`), and the various review CSVs
  (`sense_corrections.csv`, `pos_corrections.csv`, `priority_concepts.csv`).
- `main.py` — entry point for the pipeline.
- `src/yaml/` — the wordnet itself, in the same per-lexfile YAML layout as
  [english-wordnet's `src/yaml/`](https://github.com/globalwordnet/english-wordnet/tree/main/src/yaml)
  (`entries-{0,a-z}.yaml`, `noun.*.yaml`, `verb.*.yaml`, `adj.*.yaml`,
  `adv.*.yaml`, `frames.yaml`), populated as the pipeline imports senses.
  Each file starts out as an empty YAML mapping (`{}`) rather than a
  0-byte file — EWE only registers a lexfile as writable once it's parsed
  at least one YAML value, so a truly empty file silently blocks adding
  new synsets to it.
- `settings.toml` — configuration for the [EWE Wordnet
  Editor](https://github.com/jmccrae/ewe); paths inside it (`wordnet_source
  = "src/yaml"`, `corpus_source = "data/sga_incomplete.teanga.yaml"`) are
  relative to this file, so the repo can be opened directly from EWE's
  desktop app "Open Wordnet Folder" picker, or served with `dx serve` from
  a checkout of `ewe_dioxus` pointed at this directory. `wordnet.db`/
  `corpus.db`, the databases EWE builds from `src/yaml/`/`corpus_source`,
  are git-ignored and rebuilt locally on first run.
- `branding/` — EWE's `logo`/`theme` for this project: the [Four
  Provinces Flag](https://commons.wikimedia.org/wiki/File:Four_Provinces_Flag.svg)
  (© [Caomhan27](https://commons.wikimedia.org/wiki/User:Caomhan27),
  [CC BY-SA 3.0](https://creativecommons.org/licenses/by-sa/3.0/deed.en)),
  used both as the logo and as the source of `theme.css`'s palette - the
  flag's dark green (Leinster's field, `#003d07`) as the primary colour,
  its gold (Ulster's field and the charges throughout) as the accent.
  Kept separate from `data/`, which is corpus source/derived data, not
  branding.

## Pipeline scripts

- `scripts/conllu_to_teanga.py` — converts `data/sga_incomplete.conllu` to
  Teanga YAML (`data/sga_incomplete.teanga.yaml`), the corpus format used
  by EWE's `corpus_source` / KWIC lookups.
- `scripts/conllu_to_en_ga.py` — generates the fast_align bitext
  (`data/sga_incomplete.en-ga`): one line per sentence, pairing the Old
  Irish lemma sequence with the English `# translation` comment (tokenized
  with NLTK's `word_tokenize`), separated by ` ||| `.
- `scripts/align_corpus.py` — word-aligns `data/sga_incomplete.en-ga` with
  [fast_align](https://github.com/clab/fast_align) (a local build, path
  configurable via `--fast-align-bin`), producing
  `data/sga_incomplete.align`. Forces `OMP_NUM_THREADS=1`: fast_align
  parallelizes EM training by default, and floating-point summation order
  (hence the final alignment in close calls) depends on thread scheduling,
  so an unpinned multi-threaded run is not reproducible from one run to
  the next. fast_align's own default flags are used (not the `-d -o -v`
  symmetrization recipe from its README), since that's what matches this
  project's alignments.
- `scripts/populate_wordnet.py` — the first actual wordnet-building step.
  Reads `data/sga_incomplete.results_AD.xlsx` (WSD candidates with an
  annotator's `Correct Translation?`/`Correct Definition?` verdicts),
  keeps rows where both are accepted, plus any rejected row covered by
  `data/sense_corrections.csv` (`--corrections`) - a manually curated list
  of (lemma, wrong sense key) -> corrected sense key overrides for rows
  where the annotator's notes showed the translation was fine and only the
  WSD system's sense choice was wrong (common in this corpus, since it's
  largely Old Irish grammatical glosses and the automatic WSD often
  preferred a common sense over an available grammar-specific one).
  Resolves each English WordNet sense key to its synset via a local
  [`wn`](https://github.com/goodmami/wn) library database (`--wn-db`,
  default `~/.wn_data/wn.db`), and generates an EWE automaton script that
  creates one new synset per accepted English sense - same definition/
  lexfile/pos/ili, but with the Old Irish lemma(s) as members instead of
  the English ones (synonyms in the accepted set land in the same synset).
  Pass `--apply --ewe-bin <path to a built ewe_cli>` to actually run it
  against `--wordnet-dir` (default `.`); otherwise it just writes the
  automaton script to `--script-out` for review. Relations (hypernym,
  etc.) between the *English* synsets aren't carried over here, since this
  only imports a sparse subset of English WordNet's synsets and most
  relation targets don't exist in this wordnet yet - see
  `scripts/link_existing_synsets.py` for the ones that do.
- `scripts/link_existing_synsets.py` — run after `populate_wordnet.py
  --apply`. English WordNet relations (hypernym, attribute, similar, also)
  where *both* endpoints already have an Old Irish synset here (matched
  via `ili`, same as `annotate_corpus_senses.py`) can be added for free,
  no new translation needed - this finds them and generates an
  `add_relation` automaton script, same `--apply`/`--ewe-bin`/
  `--wordnet-dir`/dry-run-by-default shape as `populate_wordnet.py`.
- `scripts/annotate_corpus_senses.py` — run after `populate_wordnet.py
  --apply`. Adds a `sga_key` layer to `data/sga_incomplete.teanga.yaml`
  (overwritten in place by default) so EWE's corpus concordance view can
  show where each synset occurs. `data/sga_incomplete.senses` records,
  per sentence, every English content word's WSD candidates (its top
  candidate is what `results_AD.xlsx`'s Sense Key column records);
  `data/sga_incomplete.align`'s fast_align output locates the Old Irish
  token each one corresponds to; running that word's proposed sense
  through the same accepted/corrected mapping `populate_wordnet.py` uses,
  then matching its English synset's `ili` against `src/yaml/`'s own
  synsets, gives the resulting project synset id to tag that token with.
  Tags are written as sparse `[index, "sga-<synset id>"]` pairs (teanga's
  `element` layer type - see the script's docstring for why a dense
  one-entry-per-token layer doesn't work here).
- `scripts/priority_concepts.py` — read-only report, `data/
  priority_concepts.csv`, ranking which English synsets to translate next
  to grow the link structure rather than just the synset count. Two
  categories, both computed from wn.db's hypernym graph: `top_concept` -
  the untranslated members of English WordNet's `noun.Tops` file (the
  ~51 canonical "unique beginner" concepts every noun hypernym chain
  traces back to), ranked by how many existing synsets here already
  descend from it; `bridging` - everything else that's a hypernym
  (direct or transitive) of the most existing synsets here, ranked the
  same way, so translating one creates many hypernym links at once
  instead of one link per translation.

## Development

This project uses [uv](https://docs.astral.sh/uv/) for dependency
management.

```sh
uv sync
uv run main.py
```
