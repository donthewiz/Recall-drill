# Problem recipes: formats `mathpath-recipe/1` and `/2`

A recipe describes one **problem type** (e.g. "solve a quadratic by factoring") so the future Math Path add-on can generate fresh problems, check each step, name mistakes and give hints. One JSON file per recipe, named `<id>.json`, saved per chapter (`G:\My Drive\anki\college-algebra\ch03\recipes\`). Recipes are files, not Anki notes (v1). The format is general: any math-type course (statistics, precalculus, chemistry calculations) uses the same keys.

`scripts/recipe_validator.py recipes/ --cards cards.json` must pass before a recipe ships: 20 instances per recipe (fixed seeds 1000–1019), every step and the answer recomputed by SymPy.

**Which format:** `/1` covers "solve an equation, exact roots". Anything else (vertex, range, max/min, graphing, inequalities, no solution, rounded answers, applied problems that throw out a root) needs `/2` (section at the end). The validator reads both and refuses `/2` features in a `/1` file. Working examples of every `/2` feature: `evals/files/v2/` (vertex, range, max value, graph, |ax+b| < c, rational with no solution, falling object rounded).

## Keys

| Key | Meaning |
|---|---|
| `format` | `"mathpath-recipe/1"` (bump the number for breaking changes; readers check it) |
| `id` | `<course>.<topic>.<type>`, e.g. `ca.quad.solve_factoring`; cards link to it with the tag `Recipe::<id>` |
| `version` | integer, bump when the recipe changes |
| `title`, `course`, `section` | `section` = `{book, number, title}` from the textbook's table of contents |
| `sources` | where the problem type comes from (worksheet examples, practice-test items, OpenStax section + CC BY note) |
| `priority` | `high` / `medium` / `low` (worksheets, MyMathLab list and practice tests decide) |
| `prerequisites` | recipe ids that must be solid first (the prerequisite map); ids without a recipe yet are allowed (e.g. `ca.prereq.factor_trinomial`) |
| `process_card` | the process card's subject text; its steps must equal `steps[].name` word for word |
| `var` | the unknown (`"x"`); `domain`: `"complex"` (default) or `"real"` (real odd roots, extraneous roots rejected) |
| `solve_by_u` | optional: `"sqrt(x)"` etc. when SymPy should solve the problem by substitution |
| `params` | random inputs: `{"name": {"int": [lo, hi], "not": [0]}}` or `{"choice": [...]}` |
| `let` | derived values in order, keyboard form, may use earlier names and `var` (e.g. `"std": "expand((a x - p)(x - q))"`). **Pick the answer first** (roots, vertex) and build the problem from it, so numbers come out clean. |
| `constraints` | conditions every instance must meet (`"p/a != q"`, `"gcd(a, p) == 1"`, `"floor(sqrt(abs(D)))^2 != abs(D)"`) |
| `problem` | `prompt` (shown; `{tex:name}` inserts LaTeX), `equation` (keyboard form; what SymPy solves), optional `also_asked_as`, `unknown` |
| `steps` | list of `{name, result, check, show?}`; see checks below. `show` is how Math Path displays the step if it differs from `result`. Step names are **words** ("compute the x-coordinate with the vertex formula", not "compute x = -b/(2a)"): they are also the process card's blanks, and math symbols there would make it a math card |
| `answer` | `{kind, value, form, say, units?}`; `kind` = `list` / `expr` / `equation` / `interval` / `point` (same as the cards' `MathKind`) |
| `mistakes` | named mistakes: `{id, name, rule, message, applies_if?}`; rule = `{"answer_equals": template}` or `{"answer_solves": equation}`; the validator proves each rule never fires on a right answer |
| `hints` | one per step, in order hint → why: `{step, hint, why}` |

Templates: `{name}` puts in the keyboard form (in parentheses when an operator comes right before a negative or a sum: `x - {p}` → `x - (-3)`; not after `(` or `,`, so `({h}, {k})` → `(-2, -5)`); `{tex:name}` puts in LaTeX in textbook term order; `{fix3:name}` puts in a decimal rounded to 3 places (any digit 0–9). In a prompt, prefer `{tex:...}` of a whole expression (`let "inner": "a x + b"` → `{tex:inner}`) so a negative never prints as `+ -6`.

## Step checks

| `check` | Passes when |
|---|---|
| `equivalent` | `result` is an equation with the same solution set as the problem (`may_add: true` allows extra roots after squaring) |
| `factored` | `equivalent`, and the left side is a product |
| `each` | `result` is `eq1; eq2`; their solutions together are the answer |
| `solutions` | `result` is a list equal to the answer, or to the solutions of `of_equation` (in `var`) |
| `u_equation` | `result` is the equation in `u` after substituting `u` (`"u": "x^2"`), and it leads back to the answer |
| `values` | `result` is `a = 3, b = -2, …`; `names` maps them to params |
| `equal` | `result` equals the expression in `to` (a template: write `{h}`, not `h`) |
| `substitution` | every answer satisfies the original equation |
| `rejects` | each value in `result` fails the original equation (extraneous root thrown out) |
| `text` | a sentence with nothing to compute (familiarize, state) |

## Answer forms

`exact` (no decimals), `reduced_fraction`, `simplified_radical` (no square factor under √), `a+bi` (no √ of a negative), `interval` (bracket notation), and in `/2` `approx:N` (rounded to N decimal places). The answer as written must already be in the form.

Forms are checked **on the text as typed** (`verify_math.form_problems`), because SymPy simplifies while it parses: it reads `(-2 +- sqrt(88))/6` as `-1/3 ± sqrt(22)/3`. So `(-2 ± √88)/6` is "radical not simplified" and `(-2 ± 2√22)/6` is "fraction not reduced", while `(-1 ± √22)/3` and `-1/3 ± √22/3` both pass.

**Grading in Math Path:** a recipe answer is graded **value + forms** (`verify_math.check_answer(typed, key, kind, forms)`), not the cards' "same form" rule. Any correctly simplified way of writing the answer counts, and each broken form gets its own message.

## Example (abridged)

```json
{
 "format": "mathpath-recipe/1", "id": "ca.quad.solve_factoring", "version": 1,
 "title": "Solve a quadratic equation by factoring",
 "section": {"book": "Bittinger … 7e", "number": "3.2", "title": "Quadratic Equations, Functions, Zeros, and Models"},
 "prerequisites": ["ca.prereq.factor_trinomial"],
 "process_card": "Solving a quadratic equation by factoring",
 "params": {"a": {"choice": [1, 1, 1, 2, 3]}, "p": {"int": [-9, 9], "not": [0]}, "q": {"int": [-9, 9], "not": [0]}, "k": {"int": [-6, 6]}},
 "let": {"std": "expand((a x - p)(x - q))", "lhs": "std + k", "fac": "(a x - p)(x - q)", "r1": "p/a", "r2": "q"},
 "constraints": ["p/a != q", "p/a != -q", "gcd(a, p) == 1"],
 "problem": {"prompt": "Solve: {tex:lhs} = {tex:k}", "equation": "{lhs} = {k}"},
 "steps": [
  {"name": "write it in standard form (= 0)", "result": "{std} = 0", "check": "equivalent"},
  {"name": "factor", "result": "{fac} = 0", "check": "factored"},
  {"name": "set each factor equal to 0", "result": "{f1} = 0; {f2} = 0", "check": "each"},
  {"name": "solve each equation", "result": "{r1}, {r2}", "check": "solutions"},
  {"name": "check", "result": "", "check": "substitution"}],
 "answer": {"kind": "list", "value": "{r1}, {r2}", "form": ["exact", "reduced_fraction"]},
 "mistakes": [{"id": "sign_slip", "name": "sign slip", "rule": {"answer_equals": "{r1n}, {r2n}"},
               "message": "Sign slip: the factor (x - 3) = 0 gives x = 3, not -3."}],
 "hints": [{"step": "factor", "hint": "Find two binomials whose product is the left side.", "why": "A product lets you split one equation into two small ones."}]
}
```

## For Math Path (later build)

- A due recipe card opens Math Path with a fresh instance; no help = Good, hint = Hard, step shown = Again (Anki schedules).
- "Say the plan": the learner types `steps[].name` in order (same words as the Recall Drill process card).
- Faded steps: show `steps[i].show or result` for the first k steps, blank the rest.
- Mistake detection: compare the learner's answer with each `rule`; show `message`.
- OATutor (CC BY 4.0) may be used to cross-check coverage and hint wording, with attribution in `sources`; never copied.


## Format 2 (`mathpath-recipe/2`, plugin v1.1)

Everything in format 1 still applies. Added:

### Tasks (`problem.task`, default `solve`)

| Task | Reads | Answer kind | What SymPy checks |
|---|---|---|---|
| `solve` | `problem.equation`: an equation **or inequality** (`<`, `<=`, `>`, `>=`, compound `-5 < 3x+2 < 5`, `x < -1 or x > 3`) | `list`, `interval`, `none`, `all_reals` | the solution set (inequalities over the reals) |
| `vertex` | `problem.function` | `point` | (−b/2a, f(−b/2a)); also a\|x−h\|+k |
| `axis` | `problem.function` | `equation` (`x = {h}`) | x = h |
| `extreme` | `problem.function` | `expr` + `answer.type` (`minimum`/`maximum`) | the value k and that the type matches the sign of a |
| `range` / `domain` | `problem.function` | `interval` | SymPy's range / domain over the reals |
| `evaluate` | `problem.function`, `problem.at` | `expr` (or `list` with `approx:N`) | f(at) |
| `graph` | `problem.function` | `graph` | the shape, that every point is on the graph, that the first point is the vertex |

### Answer kinds and keys

| Key | Meaning |
|---|---|
| `kind: none` | value `"no solution"` (a 3.4 rational equation whose only candidate is excluded) |
| `kind: all_reals` | every real number (an identity, or `|x| > -1`) |
| `kind: graph` | `"parabola; (h, k); (x2, y2)"`: shape (`parabola`, `line`, `absolute value`, `curve`), then the vertex, then at least one more point (what MyMathLab's graph tool asks for) |
| `form: ["approx:3"]` | the value is written with 3 decimals (`{fix3:t1}`); compared within half a unit in the last place; `exact` and `approx` can't both be set |
| `reject_if` | conditions on `var` that throw a root out of the final answer, e.g. `["t < 0"]` for a time or length. Steps still see every root; a `rejects` step names the root that goes |
| `display` | the answer in course notation, e.g. `"({nb} +- sqrt({D}))/({twoa})"`. Must equal `value` and pass the forms; Math Path shows it |
| `type` | `minimum` / `maximum` for task `extreme` |

### Step checks added

| `check` | Passes when |
|---|---|
| `pm_equation` | `result` is one equation with `+-` (`x - 2 = +-sqrt(11)`); its two branches give the answer. Use it for the "take ± the square root" step instead of writing the final answer twice |
| `equivalent` on an inequality | `result` (an inequality, compound or with `or`) has the same solution set as the problem |
| `substitution` on an inequality | a number inside each piece of the answer satisfies the original, and numbers outside don't |

### Mistake rule added

| Rule | Meaning |
|---|---|
| `{"form_violation": "<form>", "example": "<template>"}` | the value is right but the written form breaks `<form>` (e.g. `reduced_fraction`, `simplified_radical`, `approx:3`). The validator proves the example has the right value **and** breaks that form, and that the key itself doesn't |
| `answer_equals` | now works for every kind (points, intervals, graphs, "no solution" recipes whose wrong answer is a number) |

### Which test items need format 2 (College Algebra Ch 3, Test Form A)

#13–#16 (inequalities, interval notation), #20 (rounded applied answer), #29 (vertex, axis, max/min, range, graph), #30 (maximum area), 3.4 rational equations with no solution.
