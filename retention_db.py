#!/usr/bin/env python3
"""
retention_db.py - Global Viewer Retention & Storytelling Knowledge Base CLI
Provides fast search, cultural filters, and script generation based on worldwide audience retention mechanics.
"""

import sys
import os
import json
import sqlite3
import argparse
import random
from typing import List, Dict, Any, Optional

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "retention_database.db")

SCHEMA = """
-- Core Mechanism Table (Cognitive & Psychological Primitives)
CREATE TABLE IF NOT EXISTS mechanisms (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    primitive_type TEXT NOT NULL, -- curiosity, loss_aversion, status_reversal, pattern_break, dramatic_irony
    cognitive_basis TEXT NOT NULL,
    risk_factor TEXT NOT NULL,
    when_to_avoid TEXT NOT NULL
);

-- Cultural / Regional Traditions
CREATE TABLE IF NOT EXISTS cultures (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    region TEXT NOT NULL, -- Asia, North America, Europe, Latin America, South Asia, Oceania
    core_tradition TEXT NOT NULL,
    pacing_signature TEXT NOT NULL,
    canonical_platforms TEXT NOT NULL
);

-- Retention Hooks & Templates Catalog
CREATE TABLE IF NOT EXISTS hooks (
    id TEXT PRIMARY KEY,
    mechanism_id TEXT,
    culture_id TEXT,
    title TEXT NOT NULL,
    archetype TEXT NOT NULL,
    target_format TEXT NOT NULL, -- shorts, longform, duanju, live_commerce
    trigger_emotion TEXT NOT NULL,
    template_structure TEXT NOT NULL,
    example_en TEXT NOT NULL,
    example_uk TEXT NOT NULL,
    original_terms TEXT, -- CJK or regional terms, e.g. 打脸, 起承転結, 막장
    visual_action TEXT NOT NULL,
    audio_action TEXT NOT NULL,
    time_window TEXT NOT NULL, -- 0-1.5s, 0-3s, 14-16s, etc.
    retention_role TEXT NOT NULL, -- scroll_stop, dropoff_prevention, loop_closure
    counter_indication TEXT NOT NULL,
    FOREIGN KEY(mechanism_id) REFERENCES mechanisms(id),
    FOREIGN KEY(culture_id) REFERENCES cultures(id)
);

-- Storytelling Frameworks (Global Narrative Architectures)
CREATE TABLE IF NOT EXISTS frameworks (
    id TEXT PRIMARY KEY,
    culture_id TEXT,
    name TEXT NOT NULL,
    origin_school TEXT NOT NULL,
    target_duration TEXT NOT NULL,
    steps_json TEXT NOT NULL,
    retention_profile TEXT NOT NULL,
    best_for TEXT NOT NULL,
    FOREIGN KEY(culture_id) REFERENCES cultures(id)
);

-- FTS5 Full-Text Search Table
CREATE VIRTUAL TABLE IF NOT EXISTS hooks_fts USING fts5(
    hook_id UNINDEXED,
    title,
    archetype,
    trigger_emotion,
    template_structure,
    example_en,
    example_uk,
    original_terms,
    tokenize = 'unicode61'
);

-- Trigram FTS5 Table for substring search (CJK & multi-character fragments)
CREATE VIRTUAL TABLE IF NOT EXISTS hooks_trigram USING fts5(
    hook_id UNINDEXED,
    content,
    tokenize = 'trigram'
);
"""

# Initial Seed Data
CULTURES_SEED = [
    ("china", "China (Duanju & Douyin)", "Asia", "Shuangdian (爽点 euphoria spikes) & Dalian (打脸 face-slapping revenge)", "Ultra-rapid, 180-220 wpm, cliffhanger every 50s", "Douyin, Kuaishou, ReelShort, DramaBox, Bilibili"),
    ("japan", "Japan (Anime & Manga)", "Asia", "Kishōtenketsu (起承転結 4-act non-conflict turn) & Telop (テロップ typography)", "Contrast pacing: absolute silence (Ma 間) followed by explosive punchline", "YouTube Japan, Nico Nico, TikTok JP, Abema"),
    ("korea", "South Korea (K-Drama & Webtoon)", "Asia", "Makjang (막장 extreme escalation) & Vertical Eye-Tracking (Webtoon descent)", "Sudden secret revelations, intense eye-lock freeze frames, frame-0 ASMR", "YouTube Shorts KR, Naver Webtoon, TikTok KR, KakaoPage"),
    ("usa", "United States (Hollywood & Creator Economy)", "North America", "MrBeast Pacing Ladder, Save the Cat beat sheet, Dan Harmon Story Circle", "Constant goal stakes, escalation every 45s, zero-filler, split-screen brainrot", "YouTube Shorts, TikTok US, Instagram Reels"),
    ("europe", "Europe & United Kingdom", "Europe", "BBC Attenborough Understated Irony & French Auteur Kuleshov Montage", "Deadpan intellectual delivery, severe visual-audio contrast, dry wit", "YouTube UK, BBC, Arte, TikTok EU"),
    ("latam", "Latin America & Brazil", "Latin America", "Telenovela Crash Zoom melodrama & Brazilian chaotic street virality", "Hyperbolic emotional stakes, rapid multi-angle zooms, Funk Carioca rhythm", "Instagram Reels BR/MX, TikTok LatAm, Kwai"),
    ("india", "India & South Asia", "South Asia", "Bollywood Triple Cut & High-Stakes Moral Dharma Dilemmas", "Three-angle impact cuts, slow-motion shock freezes, intense family stakes", "YouTube Shorts IN, Instagram Reels IN, Moj"),
    ("australia", "Australia & Wild Frontier", "Oceania", "Deadpan Danger Delivery (Lethal wildlife casualness)", "Severe danger juxtaposed with calm outback humor, raw unpolished reality", "TikTok AU, YouTube Shorts AU")
]

MECHANISMS_SEED = [
    ("curiosity_gap", "Information Gap (Loewenstein)", "curiosity", "Brain treats missing information as physical discomfort/itch that must be scratched.", "High initial click/stop rate; high dropoff if answer is anticlimactic.", "Do not use when viewer expects an immediate tutorial or fast utility."),
    ("loss_aversion", "Loss Aversion (Kahneman & Tversky)", "loss_aversion", "Losses weigh roughly twice as much as equal gains in classic estimates (Tversky & Kahneman 1992, lambda ~2.25); later estimates vary.", "Can provoke anxiety; audience fatigue if overused.", "Do not use for lighthearted entertainment or whimsical comedy."),
    ("status_reversal", "Status Inversion (Shuangdian / Dalian)", "status_reversal", "Deep emotional catharsis when an arrogant oppressor is humbled by an undercover hero.", "Can feel overly melodramatic or unrealistic if ungrounded.", "Avoid in strictly professional B2B or scholarly content."),
    ("pattern_break", "Sensory Anomaly / RAS Interrupt", "pattern_break", "Cuts, zooms and sudden sounds trigger an orienting response; surprise (a shift in expectations, not mere rarity) draws gaze (Itti & Baldi 2009).", "Transient attention only (0.5s); requires immediate narrative support.", "Avoid chaotic strobe cuts that cause cognitive nausea."),
    ("dramatic_irony", "Dramatic Irony (Hitchcock Bomb)", "dramatic_irony", "Viewer knows a critical secret that characters in the scene are completely oblivious to.", "Builds sustained agonizing suspense without needing fast cuts.", "Do not use when the surprise twist itself is the only selling point.")
]

HOOKS_SEED = [
    # China / Duanju
    ("cn_dalian_01", "status_reversal", "china", "Undercover Billionaire / Face-Slapping", "The Underdog Revenge (打脸)", "duanju", "vengeance / status catharsis",
     "They humiliated [Protagonist] for being poor, unaware that [True Status]...",
     "They threw my resume in the trash, unaware I just purchased the entire building 10 minutes ago.",
     "Вони викинули моє резюме у смітник, не підозрюючи, що я щойно викупив увесь їхній бізнес-центр.",
     "打脸 (Dalian), 爽点 (Shuangdian), 赘婿 (Son-in-law)",
     "Protagonist wearing ragged clothes picked up from floor; villain smirks and spills wine.",
     "Sound of shattered porcelain or harsh slap, followed by deep cinematic bass boom.",
     "0.0 - 2.0s", "scroll_stop & immediate narrative trap", "Avoid if audience expects documentary realism."),

    ("cn_live_01", "loss_aversion", "china", "Rapid-Fire Auction Countdown", "Hypnotic FOMO Blitz", "live_commerce", "urgency / scarcity panic",
     "3, 2, 1 — price drops by 80% for the next [X] seconds only!",
     "3, 2, 1 — the warehouse manager made an error, and this price will vanish in 15 seconds!",
     "3, 2, 1 — менеджер припустився помилки в ціні, і цей лот зникне з системи рівно за 15 секунд!",
     "秒杀 (Miaosha), 倒计时 (Countdown), 爆单",
     "Rapid hand-slap on wooden desk, physical buzzer pressed, countdown timer flashing red.",
     "Fast rhythmic vocal delivery (220 wpm), loud gavel strike sound effect.",
     "0.0 - 1.5s", "scroll_stop & purchase impulse", "Overuse degrades long-term brand trust."),

    # Japan / Kishōtenketsu
    ("jp_kisho_01", "pattern_break", "japan", "Everyday Object Reality Fracture", "Kishōtenketsu 4-Act Turn (起承転結)", "shorts", "wonder / cognitive dissonance",
     "A completely ordinary [Japanese Object], until you trigger this hidden switch...",
     "A completely ordinary Tokyo vending machine, until you press the unlabelled red coin slot...",
     "Звичайнісінький автомат із напоями в Токіо, поки ви не натиснете цю приховану кнопку без маркування...",
     "起承転結 (Kishōtenketsu), 間 (Ma), テロップ (Telop)",
     "Fixed camera angle, hyper-clean aesthetic, sudden physical transformation of object.",
     "Absolute silence for 0.4 seconds (Ma), then sharp wooden clapper (Hyoshigi) or anime chime.",
     "0.0 - 3.0s", "scroll_stop & anticipation of Ten (Twist)", "Do not rush the setup; the twist requires contrast."),

    ("jp_anime_01", "curiosity_gap", "japan", "Frozen Time Fatal Monologue", "Anime Cold Open (Za Warudo)", "shorts", "existential dread / curiosity",
     "At this exact microsecond, I realized: if [Object] drops another 2 millimeters, it's over.",
     "At this exact microsecond, I realized: if that blade falls 2 more millimeters, my career is finished.",
     "Рівно в цю мілісекунду я усвідомив: якщо це лезо опуститься ще на 2 міліметри — моє життя скінчилося...",
     "心の声 (Inner Voice), 時間停止 (Time Stop), 覚醒 (Awakening)",
     "Desaturated grey-scale freeze frame with only protagonist's eyes moving or glowing.",
     "Muffled heart-thump sound (80 Hz low-pass filter), echoing clock tick.",
     "0.0 - 2.5s", "scroll_stop & extreme stakes establishment", "Requires high-stakes visual payoff later."),

    # South Korea / Makjang
    ("kr_makjang_01", "dramatic_irony", "korea", "Absurd Secret Revelation", "Makjang Escalation (막장)", "shorts", "shock / betrayal indignation",
     "She opened her husband's secret drawer after [X] years and discovered her own death certificate.",
     "She opened her husband's private safe after 10 years of marriage and found her own death certificate dated yesterday.",
     "Вона відкрила особистий сейф чоловіка після 10 років шлюбу і знайшла власне свідоцтво про смерть, виписане вчора...",
     "막장 (Makjang), 출생의 비밀 (Birth Secret), 시월드",
     "Extreme close-up on trembling hands holding document, slow zoom into tear-filled eye.",
     "Violent high-pitch violin sting (Psycho-style) into stunned silence.",
     "0.0 - 3.0s", "scroll_stop & viral comment engagement", "Do not resolve too early; requires multi-layered drama."),

    ("kr_asmr_01", "pattern_break", "korea", "Frame-Zero Sensorial Blast", "Mukbang Ultra-Crunch ASMR", "shorts", "visceral pleasure / appetite trigger",
     "[Immediate High-Gain Audio Bite without voice greeting]",
     "[Crisp golden honey-comb chicken crackling at 85 dB into binaural microphone]",
     "[Золотава хрустка скоринка ламається прямо перед чутливим мікрофоном з першого мілісекунди]",
     "먹방 (Mukbang), 바삭바삭 (Crunchy Basak), 팅글 (Tingle)",
     "Macro-lens 4K extreme close-up of steam, sizzling oil, or cheese stretch taking 80% screen.",
     "Zero spoken words; pure uncompressed crisp audio (+4 dB boost on 4-8 kHz treble).",
     "0.0 - 1.0s", "instant thumb-stop via mirror neurons", "Useless if audio quality is mediocre or noisy."),

    # USA / MrBeast & Silicon Valley
    ("us_mrbeast_01", "curiosity_gap", "usa", "Literal Thumbnail Manifestation", "MrBeast Pacing Ladder", "shorts", "wonder / adrenaline excitement",
     "I put [Number] people inside [Extreme Condition], and the last one to leave wins [Huge Reward]!",
     "I put 100 people inside this giant laser maze, and the last person to touch a beam wins $50,000!",
     "Я закрив 100 людей у цьому лазерному лабіринті: останній, хто торкнеться променя, забирає $50 000!",
     "Retention Sentinel, Escalation Ladder, Ticking Clock",
     "Wide drone shot showing massive scale, timer graphic on screen, contestant jumping immediately.",
     "High-tempo orchestral percussion, immediate enthusiastic voice-over starting at 00:00:00.",
     "0.0 - 3.0s", "retention commitment", "Promise must be completely genuine and delivered in full."),

    ("us_brainrot_01", "pattern_break", "usa", "Dual-Hemisphere Sensory Lock", "Split-Screen Hypnotic Bait", "shorts", "passive trance / sensory saturation",
     "[Top: Compelling Story / Bottom: Flawless Kinetic Gameplay]",
     "[Top: True Crime Investigation narration / Bottom: Infinite Minecraft Parkour & Soap Cutting]",
     "[Верх: Захоплююча кримінальна історія / Низ: Безкінечний паркур Minecraft або нарізка кінетичного піску]",
     "Sensory Hijack, Split-Screen Brainrot, Kinetic Trance",
     "Strict 50/50 horizontal split; bottom half provides rhythmic perpetual motion.",
     "Narration voice (often AI ElevenLabs Adam) coupled with satisfying physical slicing Foley.",
     "0.0 - Full video", "drops scroll fatigue, boosts rewatch watch-time", "Reduces deep brand loyalty; purely algorithmic."),

    # Europe & UK
    ("eu_attenborough_01", "pattern_break", "europe", "Understated Academic Chaos", "BBC Attenborough Irony", "longform", "intellectual amusement / cognitive dissonance",
     "Delivered in a quiet, aristocratic Oxford accent: describing something utterly grotesque or shocking.",
     "In a soft, polite whisper: 'Observe this magnificent specimen as it ruthlessly devours its own siblings for lunch.'",
     "Оксамитовим, спокійним тоном професора: 'Погляньте на цю витончену істоту, яка щойно холоднокровно з'їла своїх братів.'",
     "British Dry Wit, Attenborough Pacing, Oxymoronic Contrast",
     "Slow, elegant macro panning shot of bizarre or deadly biological act.",
     "Zero background music; natural ambient field recording (bird chirps, dry leaves rustling).",
     "0.0 - 4.0s", "hypnotic scroll freeze through auditory contrast", "Requires flawless vocal tone and sophisticated vocabulary."),

    ("eu_kuleshov_01", "dramatic_irony", "europe", "Associative Mental Collision", "Kuleshov Montage (Soviet school)", "shorts", "analytical curiosity",
     "[Neutral Face Expression] + [Violent or Erotic Stimulus] = Derived Complex Emotion",
     "[Neutral staring protagonist] cut to [Sinking luxury yacht] cut back to [Protagonist's slight smile]",
     "[Нейтральний погляд героя] склейка [Палаючий контракт на мільйон] склейка [Герой робить ковток кави]",
     "Kuleshov Effect, Soviet Montage, Intellectual Cinema",
     "Strict metric cut: 0.8s face -> 0.8s event -> 0.8s face reaction.",
     "Heavy industrial synth pulse, sharp whoosh on transitions.",
     "0.0 - 2.4s", "stops scroll through cognitive assembly", "Risks confusing audiences who need explicit narration."),

    # Latin America & Brazil
    ("latam_telenovela_01", "dramatic_irony", "latam", "The Triple Crash-Zoom Melodrama", "Telenovela Freeze-Sting", "shorts", "extreme dramatic tension",
     "Crash zoom on Character A -> Crash zoom on Character B -> Crash zoom on Character C.",
     "Rapid mechanical crash zoom on bride's eyes, groom's jaw drop, mother-in-law holding open envelope.",
     "Швидкісний наїзд камери на наречену, потім на нареченого, потім на свекруху з відкритим тестом ДНК у руках.",
     "Telenovela, Crash Zoom, Dramatic Chord, Freeze Frame",
     "Fast mechanical zooms (0.4s each) accompanied by heavy camera shake.",
     "Loud orchestral brass hits or church bell toll on each zoom stop.",
     "0.0 - 2.0s", "instant viral emotional spike", "Can feel comical if not matched to genre tone."),

    # India / Bollywood
    ("in_bollywood_01", "pattern_break", "india", "The Triple Impact Replay", "Bollywood Thunder Cut", "shorts", "righteous awe / dramatic hype",
     "Show the pivotal shock moment 3 times consecutively with increasing zoom and distortion.",
     "The glass cup drops and shatters: Angle 1 (Slow-mo) -> Angle 2 (Macro ground) -> Angle 3 (Extreme wide with lightning).",
     "Чашка падає на мармур і розбивається: Ракурс 1 (повільно) -> Ракурс 2 (макро) -> Ракурс 3 (із блискавкою та громом).",
     "Triple Cut, Impact Frame, Dharma Dilemma, High Emotion",
     "Triple cut with lens flares, color saturation flash, and screen shake on each strike.",
     "Thunder crack SFX combined with dramatic glass shatter and choral chanting.",
     "0.0 - 2.5s", "sensory overwhelm & scroll disruption", "Avoid in quiet educational or minimalistic niches."),

    # Australia
    ("au_outback_01", "loss_aversion", "australia", "Lethal Danger with Outback Calm", "Aussie Deadpan Wildlife Hook", "shorts", "fear / morbid fascination",
     "Pointing camera at lethal predator: 'Just spotted this little beauty inside my morning kettle...'",
     "Casual hand holding a deadly funnel-web spider: 'Just woke up and found this cheeky bloke on my pillow, mate.'",
     "Спокійна рука тримає смертоносного павука: 'Прокинувся і знайшов ось цього красеня на своїй подушці, друзі.'",
     "Aussie Outback, Deadpan Delivery, Lethal Wildlife",
     "Vertical handheld camera, raw natural lighting, creature moving menacingly close to lens.",
     "Complete lack of dramatic music; casual laid-back Australian speaking voice.",
     "0.0 - 2.0s", "fear / curiosity", "Must be authentic; staged creatures look fake instantly."),

    # Expanded Universal & Cultural Hooks
    ("gen_contrarian_01", "pattern_break", "usa", "Myth Demolition / Stop Doing This", "The Contrarian Take", "shorts", "cognitive dissonance / curiosity",
     "Stop [Common Activity] like this. You are literally burning [Valuable Resource]...",
     "Most people think coffee gives you energy. It doesn't - it just hides the signal that you're tired...",
     "Більшість думає, що кава дає енергію. Ні - вона лише блокує сигнал втоми...",
     "Myth Buster, Contrarian, Dopamine Reset",
     "Fast hand gesture waving 'NO' in front of camera lens, big red cross icon over common item.",
     "Record scratch sound effect or buzzer, vocal pace energetic and confident.",
     "0.0 - 1.5s", "scroll_stop via contradiction", "Do not claim easily disproven medical pseudo-science."),

    ("gen_insider_01", "curiosity_gap", "europe", "Industry Professional Confession", "The Insider Secret", "shorts", "status desire / exclusive access",
     "What a [Professional] notices about your [Object] in the first 10 seconds...",
     "What a master mechanic notices about your engine in the first 10 seconds of listening...",
     "Що досвідчений автомеханік помічає у звуці вашого двигуна за перші 10 секунд огляду...",
     "Insider Secret, Professional Confession, Industry Whistleblower",
     "Point-of-view angle (POV) holding flashlight or stethoscope against mechanical part.",
     "Muffled engine rumble followed by sharp metallic tap with wrench.",
     "0.0 - 2.0s", "curiosity lock & perceived high authority", "Information must be technically verified and accurate."),

    ("gen_time_challenge_01", "loss_aversion", "usa", "Ticking Clock Under Siege", "The Impossible Time Trial", "shorts", "urgency / adrenaline anticipation",
     "Can I rebuild [Complex System] before this [Fast Candle / Timer] runs out? Timer starts now!",
     "Can I completely rebuild this dirt bike carburetor before this candle melts? Timer starts now!",
     "Чи встигну я повністю перебрати цей карбюратор до того, як розплавиться свічка? Таймер пішов!",
     "Ticking Clock, Time Trial, High Pressure",
     "Split screen showing high-speed hands working on left, macro shot of melting candle flame on right.",
     "Aggressive clock ticking audio combined with rapid tool clanking sounds.",
     "0.0 - 2.0s", "scroll_stop & retention hold through race dynamic", "Do not cheat on the timer; viewers spot cuts easily."),

    ("gen_in_media_res_01", "pattern_break", "latam", "Immediate Physical Disaster", "In Media Res Blast", "shorts", "visceral shock / survival reflex",
     "[Immediate crash or breakage at frame 0]: 'That exact second we realized the brakes were completely severed...'",
     "[Loud tire screech & sparks]: 'That exact second we realized the steering wheel was no longer connected to the front tires...'",
     "[Вереск гальм та іскри]: 'Рівно в цю секунду ми зрозуміли: кермо більше не з'єднане з передніми колесами...'",
     "In Media Res, Chaos Opening, Physical Threat",
     "Violent camera shake, debris flying toward lens, POV from inside moving cockpit.",
     "Loud physical metal screech, horn blaring, fast-cut into narrator's calm explanation.",
     "0.0 - 1.2s", "instant involuntary thumb arrest", "Must immediately explain the outcome within 5 seconds."),

    ("cn_dalian_02", "status_reversal", "china", "The Disguised Master Chef", "Culinary Status Slap (打脸)", "duanju", "vengeance / culinary awe",
     "The arrogant manager kicked the dirty vagrant out of the kitchen, until the master chef bowed...",
     "The arrogant restaurant owner threw soup at the homeless old man, until the 3-star Michelin inspector recognized him...",
     "Зарозумілий власник ресторану вилив помиї на бездомного дідуся, поки шеф-кухар не впізнав легенду кулінарії...",
     "打脸 (Dalian), 厨神 (Kitchen God), 逆袭 (Counter-attack)",
     "Old man catches flying plate with one finger without spilling a single drop of sauce.",
     "Whoosh sound of sudden catch, loud gasp from surrounding kitchen staff.",
     "0.0 - 2.5s", "scroll_stop & anticipation of revenge", "Overly cartoony acting damages emotional investment."),

    ("jp_kisho_02", "pattern_break", "japan", "The Hidden Ancient Craft", "Kishōtenketsu Artifact Turn", "shorts", "zen awe / curiosity",
     "He has polished this single piece of wood for 40 years. When asked what flaw remained, he did this...",
     "He has polished this Japanese teapot for 40 years. When asked what flaw remained, he took a hammer and shattered it...",
     "Він шліфував цей дерев'яний чайник 40 років. Коли його запитали про недолік — він узяв молоток і розбив його вщент...",
     "職人 (Shokunin), 起承転結, 破調 (Hacho - Fracture)",
     "Extreme macro close-up of polished wood surface reflecting narrator's eye, followed by violent hammer impact.",
     "Rhythmic soft sandpaper scrubbing sound, suddenly shattered by deafening wooden crack.",
     "0.0 - 3.0s", "profound surprise & cognitive search", "Requires authentic craft footage."),

    ("kr_makjang_02", "dramatic_irony", "korea", "The DNA Lab Phone Call", "Makjang Medical Betrayal", "shorts", "existential shock / outrage",
     "The doctor locked the clinic door and whispered: 'This DNA sample does not belong to a human.'",
     "The lab director pulled me into the vault and whispered: 'Your child's DNA profile matches the billionaire who died 20 years ago.'",
     "Директор лабораторії затягнув мене в кабінет і прошепотів: 'ДНК твоєї дитини на 100% збігається з олігархом, який загинув 20 років тому.'",
     "막장 (Makjang), 반전 (Reversal), 출생의 비밀",
     "Fluorescent lab lights buzzing, doctor sliding manila folder across steel desk with trembling hands.",
     "Fluorescent light buzz SFX, deep echoing heartbeat, whispers in Korean/English.",
     "0.0 - 3.0s", "unbreakable dramatic hook", "Must escalate stakes progressively every 12 seconds."),

    ("eu_noir_01", "pattern_break", "europe", "Nordic Silence & Menace", "Nordic Noir Tension", "longform", "dread / psychological immersion",
     "No music. Just howling Arctic wind and boots crunching on fresh snow: 'They found the car 40 miles inside the restricted border...'",
     "No music. Just icy wind: 'They found the empty diplomat car frozen solid 40 miles inside the exclusion zone...'",
     "Повна відсутність музики. Лише крижаний вітер: 'Машину посла знайшли замерзлою на смерть за 40 миль у зоні відчуження...'",
     "Nordic Noir, Cold Palette, Acoustic Isolation",
     "Desaturated blue ice landscape, single pair of black tire tracks disappearing into snowy fog.",
     "Pure wind Foley (filtered pink noise) and heavy breathing through scarf.",
     "0.0 - 3.5s", "atmospheric trance & anxiety lock", "Does not fit fast-paced meme accounts."),

    ("universal_loop_01", "curiosity_gap", "usa", "The Infinite Sentence Möbius Loop", "Seamless Loop Engine", "shorts", "endless curiosity / algorithmic rewatch",
     "Ending sentence flows grammatically into the opening sentence, so a rewatch starts seamlessly.",
     "Ending line: '...and that's because caffeine doesn't actually...' -> Opening line: '...give you energy - it hides the signal that you're tired!'",
     "Фінальна репліка: '...а все тому, що кофеїн насправді...' -> Початок: '...не додає енергії, а лише блокує сигнал втоми!'",
     "Seamless Loop, Infinite Retention, Sentence Bridge",
     "Exact match cut: narrator's hand position, head tilt, and room lighting are identical at T_end and T_0.",
     "Continuous background beat that wraps seamlessly across frame 0 without beat disruption.",
     "Final 2s -> 0.0s", "seamless rewatch (no source shows loops lift distribution)", "Loop sentence must make complete logical sense in both directions.")
]

FRAMEWORKS_SEED = [
    ("fw_wedge", "usa", "WEDGE Short-Form Engine", "Synthesis of US creator advice (not a named method of any creator)", "30-50s",
     json.dumps([
         {"step": "W (Wedge)", "time": "0-3s", "goal": "Sharp stop-the-scroll assertion or visual anomaly."},
         {"step": "E (Escalation)", "time": "3-15s", "goal": "Rapid progression toward goal while hitting obstacle 1."},
         {"step": "D (Dilemma/Turn)", "time": "where your own retention curve dips", "goal": "Twist or stakes shift; there is no universal 15s cliff."},
         {"step": "G (Gold/Payoff)", "time": "25-45s", "goal": "Genuine, explosive fulfillment of the opening promise."},
         {"step": "E (End-Early)", "time": "Final second", "goal": "Zero goodbye filler; hard cut on peak word for seamless loop."}
     ]),
     "Hypothesis: measure on your own retention curve",
     "Educational, viral life-hacks, challenge Shorts"),

    ("fw_duanju_shuangdian", "china", "Duanju Shuangdian Loop", "Chinese Vertical Drama (ReelShort / Kuaishou)", "60-90s",
     json.dumps([
         {"step": "Public Humiliation", "time": "0-15s", "goal": "Protagonist severely insulted or suppressed by arrogant antagonist."},
         {"step": "Hidden Signal", "time": "15-30s", "goal": "Clue revealed to audience showing protagonist is secret supreme power."},
         {"step": "The Arrival", "time": "30-45s", "goal": "Billionaire motorcade or army arrives; antagonist is terrified."},
         {"step": "Dalian (Face-Slap)", "time": "45-65s", "goal": "Total status inversion; antagonist falls to knees begging."},
         {"step": "Monetization Cliffhanger", "time": "65-75s", "goal": "Deadly secret phone call or emergency that forces next episode purchase."}
     ]),
     "Extreme emotional volatility; completion figures unsourced",
     "Micro-dramas, fiction, narrative reels"),

    ("fw_kishotenketsu", "japan", "Kishōtenketsu 4-Act Balance", "Japanese Classical Literature & Manga", "20-40s",
     json.dumps([
         {"step": "Ki (起 - Intro)", "time": "0-5s", "goal": "Establish calm, relatable baseline everyday scenario."},
         {"step": "Shō (承 - Follow)", "time": "5-15s", "goal": "Develop the scenario normally; build pleasant comfort."},
         {"step": "Ten (転 - Twist)", "time": "15-28s", "goal": "Introduce sudden, completely orthogonal element that reframes context."},
         {"step": "Ketsu (結 - Synthesis)", "time": "28-35s", "goal": "Synthesize the two worlds together into witty or profound closure."}
     ]),
     "Hypothesis: gentle curve; not measured",
     "Visual storytelling, animation, artistic humor, cooking")
]

def init_db():
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    cursor.executescript(SCHEMA)

    # Seeds are the source of truth: drop rows whose ids were removed from them
    for table in ("hooks", "frameworks", "mechanisms", "cultures"):
        cursor.execute(f"DELETE FROM {table}")

    # Insert Cultures
    cursor.executemany("INSERT OR REPLACE INTO cultures VALUES (?,?,?,?,?,?)", CULTURES_SEED)
    # Insert Mechanisms
    cursor.executemany("INSERT OR REPLACE INTO mechanisms VALUES (?,?,?,?,?,?)", MECHANISMS_SEED)
    # Insert Hooks
    cursor.executemany("INSERT OR REPLACE INTO hooks VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", HOOKS_SEED)
    # Insert Frameworks
    cursor.executemany("INSERT OR REPLACE INTO frameworks VALUES (?,?,?,?,?,?,?,?)", FRAMEWORKS_SEED)

    # Populate FTS5 and Trigram
    cursor.execute("DELETE FROM hooks_fts")
    cursor.execute("DELETE FROM hooks_trigram")
    for hook in HOOKS_SEED:
        hook_id = hook[0]
        title = hook[3]
        archetype = hook[4]
        trigger_emotion = hook[6]
        template = hook[7]
        ex_en = hook[8]
        ex_uk = hook[9]
        cjk_terms = hook[10] or ""
        
        cursor.execute("""
            INSERT INTO hooks_fts(hook_id, title, archetype, trigger_emotion, template_structure, example_en, example_uk, original_terms)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (hook_id, title, archetype, trigger_emotion, template, ex_en, ex_uk, cjk_terms))

        full_text_blob = f"{title} {archetype} {template} {ex_en} {ex_uk} {cjk_terms} {trigger_emotion}"
        cursor.execute("INSERT INTO hooks_trigram(hook_id, content) VALUES (?, ?)", (hook_id, full_text_blob))

    conn.commit()
    conn.close()

def query_hooks(query_str: Optional[str] = None,
                region: Optional[str] = None,
                format_filter: Optional[str] = None,
                emotion: Optional[str] = None) -> List[Dict[str, Any]]:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    conditions = []
    params = []

    if region:
        conditions.append("(c.id = ? OR c.region LIKE ?)")
        params.extend([region.lower(), f"%{region}%"])

    if format_filter:
        conditions.append("h.target_format = ?")
        params.append(format_filter.lower())

    if emotion:
        conditions.append("h.trigger_emotion LIKE ?")
        params.append(f"%{emotion}%")

    matched_ids = set()
    if query_str and query_str.strip():
        q = query_str.strip()
        # 1. Try standard FTS5
        try:
            fts_rows = cursor.execute("SELECT hook_id FROM hooks_fts WHERE hooks_fts MATCH ?", (q,)).fetchall()
            for r in fts_rows:
                matched_ids.add(r["hook_id"])
        except Exception:
            pass

        # 2. Try trigram FTS5 (for substrings / CJK words like 打脸)
        try:
            tri_rows = cursor.execute("SELECT hook_id FROM hooks_trigram WHERE hooks_trigram MATCH ?", (q,)).fetchall()
            for r in tri_rows:
                matched_ids.add(r["hook_id"])
        except Exception:
            pass

        # 3. Fallback LIKE search for short CJK / symbols
        like_rows = cursor.execute("""
            SELECT id FROM hooks 
            WHERE title LIKE ? OR example_en LIKE ? OR example_uk LIKE ? OR original_terms LIKE ?
        """, (f"%{q}%", f"%{q}%", f"%{q}%", f"%{q}%")).fetchall()
        for r in like_rows:
            matched_ids.add(r["id"])

        if matched_ids:
            placeholders = ",".join("?" for _ in matched_ids)
            conditions.append(f"h.id IN ({placeholders})")
            params.extend(list(matched_ids))
        else:
            conn.close()
            return []

    where_clause = ""
    if conditions:
        where_clause = "WHERE " + " AND ".join(conditions)

    sql = f"""
        SELECT 
            h.id, h.title, h.archetype, h.target_format, h.trigger_emotion,
            h.template_structure, h.example_en, h.example_uk, h.original_terms,
            h.visual_action, h.audio_action, h.time_window, h.retention_role,
            h.counter_indication,
            c.name as culture_name, c.region,
            m.name as mechanism_name, m.cognitive_basis
        FROM hooks h
        JOIN cultures c ON h.culture_id = c.id
        JOIN mechanisms m ON h.mechanism_id = m.id
        {where_clause}
        ORDER BY h.id
    """
    rows = cursor.execute(sql, params).fetchall()
    results = [dict(r) for r in rows]
    conn.close()
    return results

def get_random_hook() -> Optional[Dict[str, Any]]:
    all_hooks = query_hooks()
    return random.choice(all_hooks) if all_hooks else None

def generate_blueprint(topic: str, culture: str = "usa", duration: str = "45s") -> str:
    culture_clean = culture.strip().lower() if culture else "usa"
    hooks = query_hooks(region=culture_clean)
    if not hooks:
        hooks = query_hooks()
    chosen_hook = random.choice(hooks) if hooks else None
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    fw = conn.cursor().execute("SELECT * FROM frameworks WHERE lower(culture_id) = ? OR lower(culture_id) LIKE ?", 
                               (culture_clean, f"%{culture_clean}%")).fetchone()
    if not fw:
        fw = conn.cursor().execute("SELECT * FROM frameworks LIMIT 1").fetchone()
    conn.close()

    steps = json.loads(fw["steps_json"]) if fw else []

    out = []
    out.append(f"===========================================================")
    out.append(f"🎬 PRODUCTION RETENTION BLUEPRINT ({duration})")
    out.append(f"🎯 Topic: {topic}")
    out.append(f"🌍 Cultural Style: {chosen_hook['culture_name'] if chosen_hook else culture}")
    out.append(f"🏗️ Framework: {fw['name'] if fw else 'Standard WEDGE Engine'}")
    out.append(f"===========================================================\n")

    if chosen_hook:
        out.append(f"📍 [HOOK CARD: {chosen_hook['archetype']}] (Window: {chosen_hook['time_window']})")
        out.append(f"   • English Line:  \"{chosen_hook['example_en']}\"")
        out.append(f"   • Ukrainian Line: \"{chosen_hook['example_uk']}\"")
        out.append(f"   • Visual Action:  {chosen_hook['visual_action']}")
        out.append(f"   • Audio Design:   {chosen_hook['audio_action']}")
        out.append(f"   • Neuro-Basis:    {chosen_hook['cognitive_basis']}")
        out.append(f"   • CAUTION:        {chosen_hook['counter_indication']}\n")

    out.append(f"⏱️ CHRONOLOGICAL PACING BREAKDOWN:")
    for step in steps:
        out.append(f"   [{step['time']}] {step['step']}")
        out.append(f"      👉 Target Goal: {step['goal']}")

    out.append(f"\n⚡ RETENTION SENTINEL REMINDER:")
    out.append(f"   - Cut where the action changes; no source sets a 1.5-2.0s cut rhythm.")
    out.append(f"   - Put the twist where your own retention curve dips; there is no universal 15s cliff.")
    out.append(f"   - End strictly on peak word (Zero goodbye words).")
    return "\n".join(out)

def print_hook_card(h: Dict[str, Any]):
    print(f"\n{'='*75}")
    print(f"🎯 [{h['id']}] {h['title']} | {h['archetype']}")
    print(f"🌍 Region: {h['culture_name']} ({h['region']}) | Format: {h['target_format']}")
    print(f"🧠 Mechanism: {h['mechanism_name']} | Trigger: {h['trigger_emotion']}")
    if h.get('original_terms'):
        print(f"🀄 Original Terms: {h['original_terms']}")
    print(f"{'-'*75}")
    print(f"📋 Template: {h['template_structure']}")
    print(f"🇺🇸 EN: \"{h['example_en']}\"")
    print(f"🇺🇦 UK: \"{h['example_uk']}\"")
    print(f"👁️ Visual: {h['visual_action']}")
    print(f"🔊 Audio:  {h['audio_action']} ({h['time_window']})")
    print(f"⚠️ When to avoid: {h['counter_indication']}")
    print(f"{'='*75}")

def main():
    # Windows consoles default to cp1251/cp866, which cannot encode the emoji and CJK output
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    parser = argparse.ArgumentParser(description="Worldwide Viewer Retention & Storytelling Knowledge Base CLI")
    parser.add_argument("-q", "--query", help="Search query (full text, trigram, or original terms like 打脸)")
    parser.add_argument("-r", "--region", help="Filter by culture/region (china, japan, korea, usa, europe, latam, india, australia)")
    parser.add_argument("-f", "--format", help="Filter by format (shorts, longform, duanju, live_commerce)")
    parser.add_argument("-e", "--emotion", help="Filter by emotion (curiosity, loss_aversion, shock, etc.)")
    parser.add_argument("--random", action="store_true", help="Fetch a random hook card")
    parser.add_argument("--generate", help="Generate full production blueprint for a given topic")
    parser.add_argument("--culture", default="usa", help="Culture to use with --generate")
    parser.add_argument("--init", action="store_true", help="Re-initialize the SQLite database")
    parser.add_argument("--stats", action="store_true", help="Show database inventory and coverage")

    args = parser.parse_args()

    if not os.path.exists(DB_PATH) or args.init:
        init_db()
        print(f"✅ Initialized Retention Database at {DB_PATH}")
        if args.init and not any([args.query, args.region, args.format, args.emotion, args.random, args.generate, args.stats]):
            return

    if args.stats:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        num_hooks = c.execute("SELECT COUNT(*) FROM hooks").fetchone()[0]
        num_cultures = c.execute("SELECT COUNT(*) FROM cultures").fetchone()[0]
        num_mechs = c.execute("SELECT COUNT(*) FROM mechanisms").fetchone()[0]
        num_fws = c.execute("SELECT COUNT(*) FROM frameworks").fetchone()[0]
        print(f"\n📊 RETENTION DATABASE STATUS:")
        print(f"   • Total Production Hooks: {num_hooks}")
        print(f"   • Global Cultural Schools: {num_cultures}")
        print(f"   • Cognitive Mechanisms:   {num_mechs}")
        print(f"   • Narrative Frameworks:   {num_fws}")
        conn.close()
        return

    if args.generate:
        blueprint = generate_blueprint(args.generate, culture=args.culture)
        print(blueprint)
        return

    if args.random:
        hook = get_random_hook()
        if hook:
            print_hook_card(hook)
        return

    # Normal Search
    results = query_hooks(query_str=args.query, region=args.region, format_filter=args.format, emotion=args.emotion)
    if not results:
        print("\n🔍 No hooks found matching your criteria. Try broader search terms.")
        return

    print(f"\n🔎 Found {len(results)} matching retention hooks:")
    for h in results:
        print_hook_card(h)

if __name__ == "__main__":
    main()
