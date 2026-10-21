# Prompt: chemistry questions with animations, balanced equations and applications

Paste this into Gemini, Antigravity (or any model) to write science questions
for the CBC platform. Replace the `{{…}}` lines. Each question it writes comes
back as JSON with a `chemistry` block; the platform's chemistry engine reads
that block and makes the rest itself — the lab-bench animation, the reactivity
series, the balanced equation (atom by atom), the observations and gas tests,
the real-life applications and the narrated video. The writer never writes an
equation the engine has to trust: the engine works the chemistry out, and a
key that disagrees with it is sent back.

---

You are writing assessment items for Kenya's Competency Based Curriculum (CBC).

- Grade: {{grade, e.g. Grade 9}}
- Learning area: {{Integrated Science | Chemistry}}
- Strand / sub-strand: {{e.g. Mixtures, Elements and Compounds / Metals and Alloys}}
- Specific learning outcomes: {{paste the SLOs from the KICD curriculum design}}
- Number of items: {{e.g. 12}}

## What every item is

Every item is also a short lab, an equation and a narrated walkthrough video.
Write the situation in Kenyan settings (a jua kali workshop, a school lab in
Nyeri, a farmer liming soil in Kakamega, a kettle furring up in Machakos), in
clear British English. Use British spellings (sulphate, aluminium, colour).

Mix the kinds across the batch:
- observations ("What is seen when …?")
- equations ("Write a balanced equation for …")
- balancing ("Balance: Fe + Cl2 → FeCl3")
- explanation ("Explain why copper does not react with dilute hydrochloric acid")
- applications ("Why is calcium oxide spread on acidic soil?")
- gas tests ("Describe a test for the gas given off")
- separation and reactivity ("How could iron be obtained from iron(III) chloride using sodium?")

Even a simple recall item gets a `chemistry` block, so its video shows the
reaction happening.

## The `chemistry` block (required on every item where substances meet, are heated, or an equation is asked)

```json
"chemistry": {"reactants": ["Zn", "CuSO4"], "condition": "", "focus": "observations"}
```

- `reactants`: one or two exact, case-correct formulas. Examples: `Zn`, `Mg`, `Na`,
  `CuSO4`, `FeSO4`, `FeCl3`, `AgNO3`, `Pb(NO3)2`, `BaCl2`, `KI`, `HCl`, `H2SO4`,
  `HNO3`, `CH3COOH`, `NaOH`, `KOH`, `Ca(OH)2`, `CuO`, `MgO`, `CaCO3`, `Na2CO3`,
  `NaHCO3`, `Ca(HCO3)2`, `CH4`, `C3H8`, `O2`, `Cl2`, `H2O`. Use elements as they
  react: `O2`, `Cl2`, `H2` (not `O`, `Cl`, `H`).
- One reactant means it is heated by itself (`"condition": "heat"`).
- `condition`: `""` (mixed at room temperature), `"heat"`, `"steam"`, `"molten"`
  (no water — for displacement by sodium or potassium), or `"boil"`.
- `focus`: `observations`, `equation`, `balancing`, `explain`, `application`,
  `test` or `separation`.
- An item that only asks to balance gives the equation instead of reactants:

```json
"chemistry": {"equation": "Fe + Cl2 -> FeCl3", "focus": "balancing"}
```

## Reactions the engine knows (stay inside these)

| Kind | Example | Rule |
|---|---|---|
| Metal + acid | `Mg` + `HCl` | Only metals above hydrogen; gives a salt and hydrogen |
| Metal + water | `Na` + `H2O`, `Fe` + `H2O` (steam) | K, Na, Ca with cold water; Mg, Zn, Fe with steam |
| Burning in oxygen | `Mg` + `O2`, `S` + `O2`, `CH4` + `O2` | Metals, carbon, sulphur, hydrogen, hydrocarbon fuels |
| Burning in chlorine | `Fe` + `Cl2` | Iron gives iron(III) chloride |
| Displacement | `Zn` + `CuSO4`, `Cu` + `AgNO3` | A metal displaces one below it in the reactivity series |
| Neutralisation | `HCl` + `NaOH`, `H2SO4` + `CuO` | Acid + alkali or metal oxide gives a salt and water |
| Acid + carbonate | `HCl` + `CaCO3` | Gives a salt, water and carbon dioxide |
| Precipitation | `AgNO3` + `NaCl`, `NaOH` + `CuSO4` | An insoluble product by the solubility rules |
| Heating | `CaCO3` (heat), `Ca(HCO3)2` (boil) | Carbonates break down; temporary hardness of water |

Pairs that do not react are good items too: the engine shows why (`Cu` + `HCl`:
copper is below hydrogen; `Cu` + `ZnSO4`: copper is below zinc). Never write a
reaction these rules would not give, and never name a product the engine
would not make.

## The answer must agree with the engine

- `correct_answer` (or the option marked `is_correct`) must say what the engine
  finds: the products, the balanced equation with its numbers, "no reaction"
  only when there is none.
- When the key contains an equation, write the engine's balanced form, for
  example `Mg + 2HCl → MgCl2 + H2`. State symbols are optional.
- Every wrong option carries a `distractor_rationale`: the misconception it catches.

## Output

Return only a JSON array, no preamble and no code fences. Each item:

```json
{
  "question_type": "multiple_choice | short_answer | structured",
  "stimulus_context": "A short Kenyan situation (optional)",
  "question_text": "The question",
  "options": [
    {"id": "A", "text": "…", "is_correct": true, "distractor_rationale": "Why this is right"},
    {"id": "B", "text": "…", "is_correct": false, "distractor_rationale": "The misconception"}
  ],
  "correct_answer": "For short-answer and structured items: the answer",
  "marking_scheme": "Mark points, one per line",
  "chemistry": {"reactants": ["…"], "condition": "", "focus": "…"},
  "pedagogy": {"bloom_level": "Understand | Apply | Analyse | Evaluate", "max_marks": 2}
}
```

## Examples

```json
[
  {
    "question_type": "multiple_choice",
    "stimulus_context": "In a school laboratory in Nyeri, learners place a strip of zinc in blue copper(II) sulphate solution.",
    "question_text": "Which observation is made after ten minutes?",
    "options": [
      {"id": "A", "text": "A reddish-brown coating forms on the zinc and the blue colour fades", "is_correct": true, "distractor_rationale": "Zinc is above copper, so it displaces copper; copper ions leave the solution."},
      {"id": "B", "text": "Bubbles of hydrogen form on the zinc", "is_correct": false, "distractor_rationale": "Confuses displacement with a metal and an acid."},
      {"id": "C", "text": "Nothing happens", "is_correct": false, "distractor_rationale": "Forgets that zinc is more reactive than copper."},
      {"id": "D", "text": "A white precipitate forms", "is_correct": false, "distractor_rationale": "Confuses displacement with precipitation."}
    ],
    "chemistry": {"reactants": ["Zn", "CuSO4"], "condition": "", "focus": "observations"},
    "pedagogy": {"bloom_level": "Apply", "max_marks": 1}
  },
  {
    "question_type": "short_answer",
    "question_text": "Balance the equation for iron burning in chlorine: Fe + Cl2 → FeCl3",
    "correct_answer": "2Fe + 3Cl2 → 2FeCl3",
    "marking_scheme": "Correct coefficients 2, 3, 2 (1 mark)",
    "chemistry": {"equation": "Fe + Cl2 -> FeCl3", "focus": "balancing"},
    "pedagogy": {"bloom_level": "Apply", "max_marks": 1}
  },
  {
    "question_type": "structured",
    "stimulus_context": "A farmer in Kakamega finds that her soil is too acidic for maize.",
    "question_text": "Explain how adding calcium carbonate (agricultural lime) to the soil helps. Write a balanced equation for its reaction with an acid such as hydrochloric acid.",
    "correct_answer": "Calcium carbonate reacts with and neutralises the acid, raising the pH. 2HCl + CaCO3 → CaCl2 + H2O + CO2",
    "marking_scheme": "Neutralises the acid / raises pH (1)\nCorrect formulae (1)\nBalanced (1)",
    "chemistry": {"reactants": ["HCl", "CaCO3"], "condition": "", "focus": "application"},
    "pedagogy": {"bloom_level": "Apply", "max_marks": 3}
  },
  {
    "question_type": "multiple_choice",
    "question_text": "A learner adds copper turnings to dilute hydrochloric acid. What happens?",
    "options": [
      {"id": "A", "text": "No reaction, because copper is below hydrogen in the reactivity series", "is_correct": true, "distractor_rationale": "Copper cannot displace hydrogen from an acid."},
      {"id": "B", "text": "Hydrogen gas is given off", "is_correct": false, "distractor_rationale": "Assumes every metal reacts with acids."},
      {"id": "C", "text": "The solution turns blue at once", "is_correct": false, "distractor_rationale": "Confuses with copper(II) oxide dissolving in acid."},
      {"id": "D", "text": "A brown precipitate forms", "is_correct": false, "distractor_rationale": "No ions react to form a solid."}
    ],
    "chemistry": {"reactants": ["Cu", "HCl"], "condition": "", "focus": "explain"},
    "pedagogy": {"bloom_level": "Understand", "max_marks": 1}
  },
  {
    "question_type": "short_answer",
    "stimulus_context": "A kettle in Machakos has a white crust (fur) inside after months of boiling borehole water.",
    "question_text": "Name the white solid and write a balanced equation for how it forms when the water is boiled.",
    "correct_answer": "Calcium carbonate. Ca(HCO3)2 → CaCO3 + H2O + CO2",
    "marking_scheme": "Calcium carbonate (1)\nBalanced equation (1)",
    "chemistry": {"reactants": ["Ca(HCO3)2"], "condition": "boil", "focus": "application"},
    "pedagogy": {"bloom_level": "Apply", "max_marks": 2}
  },
  {
    "question_type": "structured",
    "question_text": "Iron is to be obtained from iron(III) chloride using sodium. (a) Why must the iron(III) chloride be molten, not in solution? (b) Write a balanced equation.",
    "correct_answer": "(a) In solution, sodium reacts with the water first (giving sodium hydroxide and hydrogen). (b) 3Na + FeCl3 → 3NaCl + Fe",
    "marking_scheme": "(a) sodium reacts with water (1)\n(b) correct formulae (1), balanced (1)",
    "chemistry": {"reactants": ["Na", "FeCl3"], "condition": "molten", "focus": "separation"},
    "pedagogy": {"bloom_level": "Analyse", "max_marks": 3}
  }
]
```

## Check before you answer

- Every item where substances meet, are heated or an equation is asked has a
  `chemistry` block with exact formulas.
- Every reaction is in the table above, or is a pair that does not react.
- Every key agrees with the reaction the rules give, and any equation in a key
  is balanced the way the engine balances it.
- British spellings; Kenyan settings; one clear question per item.
- Nothing but the JSON array.
