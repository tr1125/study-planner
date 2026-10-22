# דוח: Study Planner, סוכן אחד ושני harnesses

> **סטטוס המדידה:**
> - **SDK: נמדד.** ההרצה המלאה בוצעה, והתוצאות ב-`results/sdk.json`.
> - **API: לא נמדד, יש הערכה.** אין לי מפתח של Claude Console, ולכן גרסת ה-API לא הורצה מול השרת.
>   הקוד שלה נבדק offline (`tests/`, 26 בדיקות עם client מדומה).
>   המספרים בעמודה **"API (הערכה\*)"** הם **הערכה ולא מדידה**: `results/api_estimate.json`, שמופק על ידי `estimate_api.py`. השיטה מתוארת בסעיף 3.
>   בדיקות ה-pass/fail של גרסת ה-API מסומנות "לא נמדד".
> - **הרצה אמיתית:** `python API/main.py --scenario scenario.json --out results/api.json` ואז `python report.py`.
>   מרגע שקיים `results/api.json`, הטבלאות עוברות אוטומטית למדידה האמיתית במקום ההערכה.

## 1. הסוכן

**Study Planner** הוא מתכנן לימודים לסטודנטית בשנה ג'. הוא שומר מועדי הגשה ובחינות, משבץ שעות לימוד קונקרטיות ביומן,
זוכר איך הסטודנטית אוהבת ללמוד, ובודק חגים בישראל לפני שהוא מתכנן.

| נושא | איך זה ממומש | API | SDK |
|---|---|---|---|
| **Tools** | 8 כלים ב-`shared/tools.py`. הכלי החיצוני הוא `check_calendar`, שקורא ל-REST API של Hebcal (חגים בישראל, בלי מפתח). | `harness/tools.py`: סכמות JSON, ולידציה של הקלט, dispatch, ושגיאות שחוזרות כ-`is_error` | `@tool` ו-`create_sdk_mcp_server`, עם `tools=[]` (אין כלים מובנים) |
| **Memory** | עובדות קצרות ב-`memory.json`. שינוי העדפה לא מוחק את הישנה אלא מסמן אותה כ-`superseded` (`replaces=M1`), כך שאפשר לראות את ההיסטוריה של ההחלטות. | `harness/memory.py` שולף בכל תור רק את העובדות הרלוונטיות לבקשה | `CLAUDE.md` שנוצר מ-`memory.json` בתחילת כל סשן ונטען דרך `setting_sources=["project"]` |
| **Context engineering** | המודל לא מקבל את כל הנתונים. מועדים, שיבוצים וזיכרון ישן הוא שולף בכלים (`list_*` ו-`recall`). | `harness/context.py`: בלוק `<context>` קטן בכל תור, עם תאריך, עובדות רלוונטיות **שעוד לא הוצגו** ותקציר מועדים **רק כשהוא השתנה** | פעם אחת לסשן: `CLAUDE.md` עם התאריך וכל הזיכרון. כל השאר נשלף בכלים. |
| **Token optimization** | פלט כלים בשורה אחת לכל פריט, למשל `D1 Algorithms exam "Final" due 2026-12-14 (Mon, in 22d) est 20h planned 3h`. התגובה של Hebcal (בערך 1KB ליום) מכווצת לשורה אחת לכל חג, וחג של כמה ימים מתמזג לטווח אחד. | מדידה לכל קריאה ולכל תור (`tokens.py`), ו-cache על system+tools ועל זנב השיחה | `ResultMessage.usage`, `model_usage` ו-`total_cost_usd`, כהפרשים בין תורות |

## 2. התרחיש

`scenario.json` מורכב מ-7 פניות בשני סשנים. סשן 2 רץ על **מופע חדש** של הסוכן, שטוען מהדיסק את הזיכרון ואת המצב, אבל לא את השיחה.

| # | סשן | בקשה | מה זה בודק |
|---|---|---|---|
| 1 | s1 | הוספת 3 מועדים | שימוש בכלים (במקביל) |
| 2 | s1 | "אני אף פעם לא לומדת בשישי, הכי טוב בבוקר 08–12, לא יותר מ-3 שעות" | שמירה לזיכרון |
| 3 | s1 | בדיקת חגים 1–20.12 ושיבוץ 2 בקרים ל-OS | הכלי החיצוני ושיבוץ לפי ההעדפות |
| 4 | s2 | "מה אתה זוכר על איך שאני לומדת?" | שליפה מהזיכרון בסשן חדש |
| 5 | s2 | 3 שיבוצים לאלגוריתמים בשבוע הבא | שימוש בזיכרון בפועל, וגם חנוכה באמצע השבוע |
| 6 | s2 | "שבץ 5 שעות ביום שישי 11.12" | **בקשה שסותרת שתי העדפות שמורות** |
| 7 | s2 | "שיניתי דעתי: שישי בסדר, אבל נשארים 3 שעות" | עדכון הזיכרון (supersede) ואז ביצוע |

10 בדיקות pass/fail. **8 מהן קוראות את המצב השמור** (`state.json` / `memory.json`, בצילום מצב אחרי כל תור), ושתיים בלבד קוראות את טקסט התשובה או את רשימת הכלים.

<!-- AUTO:checks -->
| בדיקה | מה נבדק | API (הערכה*) | SDK |
|---|---|:-:|:-:|
| `deadlines_saved` | All three deadlines are persisted with the right due dates | לא נמדד | ✅ |
| `preferences_saved` | Session 1 saved the three study preferences to long-term memory | לא נמדד | ✅ |
| `external_tool_used` | The external holiday API (check_calendar) was called in session 1 | לא נמדד | ✅ |
| `os_sessions_follow_prefs` | >=2 OS sessions this week, mornings only (08:00-12:00), not Friday, <=3h | לא נמדד | ✅ |
| `memory_recalled_in_s2` | A fresh agent instance in session 2 recalls all three preferences | לא נמדד | ✅ |
| `algo_sessions_follow_prefs` | Session 2: >=3 Algorithms sessions next week that obey the remembered preferences | לא נמדד | ✅ |
| `conflict_not_executed` | A request contradicting saved preferences (Friday, 5h) is not executed blindly | לא נמדד | ✅ |
| `preference_updated` | After confirmation the Friday fact is superseded (not deleted), the 3-hour limit stays active | לא נמדד | ✅ |
| `friday_session_after_update` | The confirmed Friday session exists: morning, <=3h, and nothing overlaps anywhere | לא נמדד | ✅ |
| `no_overlaps` | No two scheduled sessions overlap in the final state | לא נמדד | ✅ |
<!-- /AUTO:checks -->

## 3. API מול SDK: המספרים

אותו מודל ואותו effort בשתי הגרסאות (`claude-opus-5-5`, `medium`), גרסאות ספריות נעולות (`requirements.txt` / `requirements.lock`),
וכל ריצה מתחילה ממצב נקי:
- התיקייה `runs/<harness>/` נמחקת לפני כל ריצה.
- **גם ה-prompt cache בצד השרת מתחיל ריק.** כל ריצה מוסיפה ל-system prompt תגית ריצה אקראית (`(run 3fa9…)`). התגית זהה בתוך הריצה, כך שה-cache עובד בין התורות והסשנים, ושונה בין ריצות. בלי זה, ריצה שנייה בתוך שעה קראה מה-cache את **כל** התור הראשון (7,484 טוקנים ב-read ו-0 ב-write), והמספרים יצאו טובים מדי.

<!-- AUTO:summary -->
| מדד | API (הערכה*) | SDK |
|---|---:|---:|
| input (לא מ-cache) | 0 | 2,483 |
| cache read | 42,826 | 64,407 |
| cache write | 7,368 | 8,351 |
| output | 4,327 | 4,363 |
| סה"כ טוקני prompt | 50,194 | 75,241 |
| אחוז cache (read / prompt) | 85.3% | 85.6% |
| קריאות למודל | 15 | 15 |
| קריאות לכלים | 19 | 19 |
| עלות (USD) | $0.1319 | $0.1666 |
| זמן (שניות) | לא נמדד | 51 |
| בדיקות שעברו | לא נמדד | 10/10 |
<!-- /AUTO:summary -->

"אחוז cache" = `cache_read / (input + cache_read + cache_write)`. העלות מחושבת לפי מחירי Opus 5.5: $4 input, $20 output, $0.20 cache read, ו-cache write לפי ה-TTL (ראו סעיף 5).

**\* איך חושבה הערכת ה-API** (`estimate_api.py`, אפשר לשחזר):
1. **Replay:** מתוך ה-transcript של ריצת ה-SDK חילצתי, לכל תור, את ההחלטות שהמודל קיבל בפועל: אילו כלים הוא קרא, עם אילו ארגומנטים, ומה הוא ענה.
   את ההחלטות האלה הזנתי ל-**harness האמיתי של ה-API** (`StudyAgentAPI`) דרך client מדומה. ה-harness עצמו הריץ את הכלים, בנה את בלוקי ה-context, את ה-cache breakpoints ואת ההיסטוריה, וכל request שהוא היה שולח נרשם.
2. **כיול:** הבקשה הראשונה בכל סשן של ה-SDK גלויה במלואה ב-transcript (system, כלים, הודעות), וגודלה האמיתי בטוקנים ידוע מה-usage. מזה יצא יחס של 1.78 תווים לטוקן.
   היחס כולל גם תקורה קבועה, כמו פורמט הכלים, ולכן הוא נמוך מהמקובל לאנגלית.
3. **המרה:** את ה-system, הכלים ותוכן המשתמש (כולל תוצאות כלים ובלוקי context) המרתי לטוקנים לפי היחס הזה.
   הודעות המודל עצמו נספרו לפי ה-output tokens האמיתיים שלהן מריצת ה-SDK, כי אלה כוללים thinking שנשלח שוב כ-input בקריאות הבאות.
   על כל זה הפעלתי את כללי ה-cache של ה-API: breakpoints של 5 דקות, ו-system+tools שעדיין חמים בתחילת סשן 2.

**הנחות ומגבלות של ההערכה:**
- היא מניחה שהמודל היה מקבל **בדיוק אותן החלטות** בשתי הגרסאות. בפועל המודל לא דטרמיניסטי, ובריצה אמיתית מספר הקריאות לכלים עשוי להשתנות.
- היחס בין תווים לטוקנים כויל על בקשות SDK, ששיעור התקורה הקבועה בהן גבוה יותר.
- לכן אני מעריכה **אי-ודאות של ±25%** בטוקני ה-prompt של ה-API.
- ההבדל בין הגרסאות (כ-1.5–3K טוקנים לכל קריאה) גדול מאי-הוודאות הזאת, ולכן **הכיוון של ההשוואה** (ה-SDK שולח יותר) אמין יותר מהמספר המדויק.

### פירוט לכל תור

<!-- AUTO:turns -->
| תור | סשן | API (הערכה*): prompt / out / קריאות / $ | SDK: prompt / out / קריאות / $ | כלים (SDK) |
|---:|---|---|---|---|
| 1 | s1 | 4,514 / 640 / 2 / $0.0260 | 8,780 / 660 / 2 / $0.0331 | add_deadline, add_deadline, add_deadline |
| 2 | s1 | 6,213 / 413 / 2 / $0.0130 | 9,215 / 413 / 2 / $0.0157 | remember, remember, remember |
| 3 | s1 | 12,071 / 948 / 3 / $0.0269 | 16,585 / 948 / 3 / $0.0317 | check_calendar, list_sessions, schedule_session, schedule_session |
| 4 | s2 | 2,080 / 175 / 1 / $0.0053 | 4,562 / 191 / 1 / $0.0121 | - |
| 5 | s2 | 8,389 / 1,151 / 3 / $0.0310 | 12,680 / 1,151 / 3 / $0.0378 | list_deadlines, list_sessions, check_calendar, schedule_session, schedule_session, schedule_session |
| 6 | s2 | 3,716 / 208 / 1 / $0.0065 | 5,297 / 208 / 1 / $0.0080 | - |
| 7 | s2 | 13,211 / 792 / 3 / $0.0234 | 18,122 / 792 / 3 / $0.0282 | remember, check_calendar, schedule_session |
<!-- /AUTO:turns -->

## 4. שורות קוד לכל חלק ב-harness

שורות לוגיות: בלי שורות ריקות, הערות ו-docstrings (`shared/loc.py`).
ב-API נספר הקובץ `API/harness/<part>.py`. ב-SDK נספרות שורות הקוד שמסומנות `# replaces: <part>`.
שורה שמחליפה שני חלקים (למשל `# replaces: memory, context`) נספרת בשניהם.

<!-- AUTO:loc -->
| חלק ב-harness | API (קובץ ב-harness/) | SDK (שורות `# replaces:`) |
|---|---:|---:|
| loop | 41 | 4 |
| tools | 67 | 8 |
| history | 68 | 4 |
| memory | 30 | 4 |
| context | 66 | 2 |
| compaction | 27 | 0 |
| caching | 27 | 0 |
| tokens | 45 | 8 |
| **סה"כ חלקי harness** | **371** | **30** |
| קבצי חיווט (לא harness) | agent.py 55, main.py 53 | סה"כ קבצי SDK: agent.py 117, main.py 47, tools.py 19 |
| **סה"כ קוד בגרסה** | **479** | **183** |
<!-- /AUTO:loc -->

**מה ה-SDK חסך:**
- **loop, compaction, caching:** הלולאה היא `client.query()` + `receive_response()`. compaction ו-caching הם אפס שורות, כי Claude Code עושה אותם לבד.
- **history:** ב-API זה log append-only עם replay, rollback לתור שנקטע באמצע וסיכומי compaction. ב-SDK זה `resume=session_id`, כלומר קובץ JSON קטן שממפה שם סשן ל-id.
- **tools:** בלי ולידציה ידנית ובלי dispatch. שגיאה לא צפויה בתוך handler חוזרת למודל כ-`isError` דרך שכבת ה-MCP.
- **עבודה שלא רואים בספירת השורות:** ב-API צריך לדעת להחזיר thinking blocks בלי לשנות אותם, לשמור את ההיסטוריה append-only (preserved thinking ב-Opus 5.5), לשים breakpoints בלי לשנות את ההיסטוריה השמורה, ולסגור tool_use פתוחים כשהלולאה נעצרת. ב-SDK אף אחד מאלה לא היה צריך לעניין אותי.

**ומה לא נחסך:** חלק ה-tokens ב-SDK לא קטן (8 שורות לעומת 45). ה-SDK מחזיר `total_cost_usd` ו-`model_usage` **מצטברים לכל הסשן**, ואילו `usage` מכסה רק את המודל הראשי ורק את התור הנוכחי. כדי לקבל מספרים לכל תור שכוללים גם את הקריאות הצדדיות של Claude Code, הייתי צריכה לחשב הפרשים בעצמי. גילינו את זה רק בהרצה אמיתית.

## 5. איפה ה-SDK עלה יותר טוקנים, איפה פחות, ולמה

מה שבדקתי ישירות ב-transcript שClaude Code שומר (`~/.claude/projects/<cwd>/<session>.jsonl`, רשומות `api-request-shape` ו-`attachment`):

**איפה ה-SDK עולה יותר:**
1. **cache write במחיר כפול.** Claude Code מסמן את ה-breakpoints שלו עם `ttl: "1h"`, ו-cache write של שעה עולה פי 2 מ-input ($8/MTok), לעומת פי 1.25 ($5/MTok) ב-TTL של 5 דקות שבחרתי ב-API.
   כל ה-cache writes בריצת ה-SDK היו מסוג `ephemeral_1h` (רואים את זה ב-`usage.cache_creation` ב-transcript). ב-agent loop שהקריאות בו מגיעות בהפרש של שניות, 1h לא קונה כלום.
   בריצה שלנו: 8,351 טוקני cache write × $3/MTok הפרש = **בערך $0.025, כ-15% מהעלות הכוללת של ה-SDK ($0.167)**.
2. **עטיפה קבועה סביב ה-prompt שלי.** הבלוק `"You are a Claude agent, built on Anthropic's Claude Agent SDK."` מגיע לפני ה-system prompt שלי. אחריו באים system-reminders:
   בלוק Environment (תיקיית עבודה, פלטפורמה, ו-"Shell: PowerShell; Bash tool also available", למרות ש-`tools=[]`), זהות המודל, **האימייל של החשבון**, התאריך האמיתי של המחשב, ותזכורת `<total_tokens>` **שמתווספת לכל קריאה** למודל.
3. **קריאה נסתרת ל-Haiku בכל סשן.** Claude Code מייצר כותרת לסשן (`ai-title`) עם `claude-haiku-5-5`, בערך 1,170 טוקני input לסשן. העלות זניחה (בערך $0.0001), אבל זו קריאה שלא ביקשתי, והיא לא מופיעה ב-`ResultMessage.usage` אלא רק ב-`model_usage`.
4. **שמות כלים ארוכים יותר:** `mcp__study__schedule_session` במקום `schedule_session`, בכל tool_use ובהגדרות הכלים.
5. **כל הזיכרון בכל סשן.** `CLAUDE.md` נטען במלואו, בלי קשר לבקשה. ב-API, `memory.py` שולף רק עובדות רלוונטיות ו-`context.py` לא שולח שוב עובדה שכבר הוצגה בשיחה. עם 3–4 עובדות ההבדל זניח, אבל הוא גדל ליניארית עם הזיכרון.

**איפה ה-SDK עולה פחות או אותו דבר:**
1. **אין בלוק context בכל תור.** ב-API, `context.py` מוסיף בלוק `<context>` לתור הראשון ולכל תור שבו משהו השתנה (עובדה חדשה, מועד חדש). ב-SDK אין עלות כזאת לכל תור. במקומה המודל קורא ל-`list_deadlines` כשהוא צריך, כמו בתור 5.
2. **סשן חדש מתחיל חם.** בתחילת סשן 2 Claude Code קרא מה-cache את התחילית שנכתבה בסשן 1 (העטיפה + ה-system prompt + הכלים, עם TTL של שעה). ה-API יקבל את אותו דבר רק אם סשן 2 מתחיל תוך 5 דקות מהקריאה האחרונה. בתרחיש שלנו זה המצב, אבל במציאות, כשבין הסשנים עוברים שעות, אף אחד מהשניים לא נהנה מזה.
3. **input לא-מוטמן כמעט אפס.** כל קריאה של Opus בריצת ה-SDK שילמה בערך 2–6 טוקני input מלאים, וכל השאר היה cache read או write. כל ה-input המלא שבטבלה הוא של קריאות ה-Haiku. ה-breakpoint האוטומטי על סוף השיחה עושה בדיוק מה שעשיתי ידנית ב-`caching.py`.

**שורה תחתונה במספרים** (SDK נמדד, API לפי ההערכה מסעיף 3):

| | API (הערכה) | SDK (נמדד) | ההפרש |
|---|---:|---:|---:|
| טוקני prompt | ~50K | 75K | ה-SDK שולח בערך פי 1.5 |
| עלות | ~$0.13 | $0.17 | ה-SDK יקר בערך ב-25% |

מאיפה ההפרש:
- **בערך 2,400 טוקנים** הם קריאות ה-Haiku, אחת לכל סשן.
- **השאר, בערך 1.5K טוקנים לכל אחת מ-15 הקריאות**, הוא העטיפה של Claude Code. זה ברור במיוחד בתור 4, שבו יש תשובה אחת בלי כלים: בערך 2.1K טוקנים ב-API מול 4.6K ב-SDK.
- **בעלות** מצטרפת לזה פרמיית ה-cache של שעה, כ-$0.025.

**כמות העבודה של המודל זהה:** output, מספר קריאות ומספר קריאות לכלים. זה נובע מההנחה של ה-replay, כלומר שהמודל מקבל את אותן החלטות, ולא ממדידה של ה-API.

## 6. על מה הייתה לי שליטה ב-API ואיבדתי ב-SDK

| נושא | API | SDK |
|---|---|---|
| **מה המודל רואה** | כל בייט ב-request: רק ה-system prompt, הכלים וההיסטוריה שלי | Claude Code מוסיף עטיפה ו-system-reminders שאי אפשר לכבות, כולל **האימייל של המשתמשת** ו**תאריך המחשב**. התאריך מתנגש ב-`planner_date` של התרחיש, והייתי צריכה להוסיף ל-system prompt הוראה מפורשת להתעלם מכל תאריך אחר. |
| **context לכל תור** | אני מחליטה בכל תור מה להוסיף (`context.py`) | `CLAUDE.md` נקרא פעם אחת בתחילת הסשן. עובדה שנשמרת באמצע סשן לא תיכנס אליו עד הסשן הבא (המודל יודע עליה כי הוא קרא ל-`remember`). אפשר להוסיף hook של `UserPromptSubmit`, אבל זה בדיוק הקוד שה-SDK היה אמור לחסוך. |
| **caching** | מיקום breakpoints ו-TTL לפי האופי של השיחה | קבוע: 1h ובמחיר כפול |
| **compaction** | סף משלי (60K), prompt סיכום משלי, והסיכום נשמר בלוג שלי | אוטומטי, הסף והסיכום לא בשליטתי |
| **היסטוריה** | log append-only שלי, בתוך הפרויקט, עם פורמט ידוע ו-replay | ב-`~/.claude/projects/`, מחוץ לפרויקט, בפורמט פנימי של Claude Code. אפשר רק `resume` לפי id. |
| **הלולאה** | אני רואה כל `stop_reason`, יכולה להתערב בין איטרציות, וקובעת מגבלה | `max_turns`, ומעבר לזה hooks |
| **מדידה** | usage מדויק לכל קריאה | `usage` מכסה רק את המודל הראשי, וה-cost מצטבר לכל הסשן. כדי לקבל מספר לכל קריאה צריך לקרוא את ה-transcript. |
| **שקיפות לגרסאות** | `anthropic==2.1.0`, ה-request הוא מה שכתבתי | ההתנהגות תלויה ב-CLI שארוז בתוך ה-SDK (`2.1.308`). שדרוג של ה-SDK עלול לשנות את העטיפה, את ה-TTL ואת הקריאות הנסתרות בלי שינוי בקוד שלי. |
| **סביבה** | התהליך שלי בלבד | תהליך Claude Code יורש משתני סביבה. הרצה מתוך session של Claude Code העבירה לו `CLAUDECODE=1`, `CLAUDE_CODE_SESSION_ID` ועוד, ולכן את הריצה הסופית הרצתי עם סביבה נקייה (`env -i`). |

## 7. איזו גרסה הייתי בוחרת לסוכן הזה

**ל-Study Planner כמו שהוא, סוכן אישי שרץ אצלי: גרסת ה-SDK.**
- הוא עשה את כל מה שהתרחיש דורש (10/10 בדיקות) עם 30 שורות "harness" במקום 371. compaction, caching ו-resume חסינים יותר ממה שכתבתי בעצמי, כי הם נבדקו על מיליוני סשנים.
- הוא רץ על ה-login שלי ב-Claude Code, כך שלשימוש אישי אין חיוב לפי טוקן, וההבדל בעלות לכל טוקן פחות רלוונטי.
- המחירים שלו (עטיפה קבועה, cache במחיר כפול, קריאת Haiku) קטנים בסדר הגודל של הסוכן הזה, שיש בו 7 תורות קצרות ו-8 כלים.

**הייתי עוברת ל-API אם הסוכן היה הופך למוצר לסטודנטים אחרים**, משלוש סיבות:
(1) פרטיות: ב-SDK האימייל של מי שמריץ את התהליך נכנס ל-context, ואין לי שליטה על זה.
(2) עלות: בתנועה גבוהה ה-cache write הכפול וה-context של כל הזיכרון בכל סשן מצטברים, ושם `memory.py` / `context.py` הסלקטיביים משתלמים.
(3) דטרמיניזם: ההתנהגות לא אמורה להשתנות בגלל שדרוג של CLI.

## 8. מגבלות

- **גרסת ה-API לא נמדדה. המספרים שלה הם הערכה** (סעיף 3, אי-ודאות של ±25% בטוקני prompt), ובדיקות ה-pass/fail שלה לא רצו מול המודל.
  הקוד נבדק offline מול client מדומה שמחקה את ה-Messages API (`tests/test_api_harness.py`): tool loop מקבילי, `is_error`, שמירת thinking blocks, cache breakpoints, compaction ו-resume.
  כמו כן, ההערכה עצמה הריצה את ה-harness האמיתי מקצה לקצה על 15 קריאות.
- ריצה אחת לכל גרסה. המודל לא דטרמיניסטי, ומספר הקריאות לכלים משתנה בין ריצות. למשל, בריצת ניסיון קודמת של ה-SDK המודל קרא ל-`check_calendar` פעמיים בתור 3.
- ה-cache של העטיפה של Claude Code (הכלים ו-`"You are a Claude agent…"`) עשוי להיות משותף בין ריצות, כי הוא מגיע **לפני** תגית הריצה. זו תכונה של ה-SDK, לא של ההשוואה.
- עלות ה-SDK היא "list price" לפי `total_cost_usd`. בפועל הריצה חויבה דרך המנוי של Claude Code ולא בחיוב לפי טוקן.
