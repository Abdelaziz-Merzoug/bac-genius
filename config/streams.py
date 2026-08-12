"""Scope declaration for bac-genius: streams, subjects and the curriculum
validation reference (syllabus keyword maps).

Scope decision
--------------
bac-genius targets a **single** Algerian Baccalaureate stream:
``experimental_sciences`` (شعبة علوم تجريبية). No other stream is
supported; do not add one without an explicit product decision.

Within that stream, three subjects are covered, each carrying its
official coefficient:

- SVT (علوم الطبيعة والحياة)         -- coefficient 6
- Physics (العلوم الفيزيائية)        -- coefficient 5
- Math (الرياضيات)                   -- coefficient 5

``SYLLABUS_MAPS`` is a **curriculum validation reference**: a bilingual
(Arabic/French) keyword lexicon per official syllabus topic, used by the
``validation`` package to check that content (scraped, generated, or
retrieved) plausibly belongs to a given topic. It is intentionally NOT
the primary topic tagger -- BERTopic (see ``nlp``) performs unsupervised
topic discovery/tagging on real corpora; this map only anchors that
output back onto the official syllabus for auditability and reporting.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

#: The only Baccalaureate stream in scope for this project.
STREAMS: List[str] = ["experimental_sciences"]


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """A Bac subject in scope, with its official exam coefficient."""

    code: str
    name_ar: str
    name_fr: str
    coefficient: int


SUBJECTS: List[Subject] = [
    Subject(code="svt", name_ar="علوم الطبيعة والحياة", name_fr="Sciences de la Vie et de la Terre", coefficient=6),
    Subject(code="physics", name_ar="العلوم الفيزيائية", name_fr="Sciences Physiques", coefficient=5),
    Subject(code="math", name_ar="الرياضيات", name_fr="Mathématiques", coefficient=5),
]

#: Convenience lookup: subject code -> Subject.
SUBJECTS_BY_CODE: Dict[str, Subject] = {s.code: s for s in SUBJECTS}


# ---------------------------------------------------------------------------
# Syllabus validation reference
# ---------------------------------------------------------------------------

#: subject_code -> topic_key -> language -> keyword variants.
SyllabusMap = Dict[str, Dict[str, Dict[str, List[str]]]]

SYLLABUS_MAPS: SyllabusMap = {
    "svt": {
        "protein_function_enzymes_immunity": {
            "ar": [
                "العلاقة بين البنية والوظيفة في البروتين",
                "الإنزيمات",
                "الحركية الإنزيمية",
                "الخاصية الفراغية للإنزيم",
                "المناعة",
                "المناعة الذاتية",
                "الاستجابة المناعية",
                "الأجسام المضادة",
                "المعقد المناعي",
                "الجهاز المناعي",
                "زرع الأعضاء",
                "فيروس نقص المناعة البشرية",
            ],
            "fr": [
                "relation structure-fonction des protéines",
                "enzymes",
                "cinétique enzymatique",
                "spécificité enzymatique",
                "immunité",
                "réaction immunitaire",
                "anticorps",
                "complexe immun",
                "système immunitaire",
                "greffe et rejet",
                "VIH",
                "auto-immunité",
            ],
        },
        "neural_communication": {
            "ar": [
                "التواصل العصبي",
                "العصبون",
                "المشبك العصبي",
                "الرسالة العصبية",
                "كمون الراحة",
                "كمون العمل",
                "الناقل العصبي",
                "المستقبلات الحسية",
                "الجملة العصبية",
            ],
            "fr": [
                "communication nerveuse",
                "neurone",
                "synapse",
                "message nerveux",
                "potentiel de repos",
                "potentiel d'action",
                "neurotransmetteur",
                "récepteur sensoriel",
                "système nerveux",
            ],
        },
        "energy_conversion_photosynthesis_mitochondria": {
            "ar": [
                "التحويل الطاقوي",
                "التركيب الضوئي",
                "الميتوكوندري",
                "الفسفرة التأكسدية",
                "سلسلة نقل الإلكترون",
                "الأكسدة التنفسية",
                "الكلوروبلاست",
                "ATP",
                "دورة كالفن",
            ],
            "fr": [
                "conversion d'énergie",
                "photosynthèse",
                "mitochondrie",
                "phosphorylation oxydative",
                "chaîne respiratoire",
                "chloroplaste",
                "ATP",
                "cycle de Calvin",
                "respiration cellulaire",
            ],
        },
        "geology": {
            "ar": [
                "الظاهرة الزلزالية",
                "الصفائح التكتونية",
                "الجيولوجيا",
                "المطاطية الصخرية",
                "الزلازل",
                "بنية الأرض الداخلية",
                "التكتونية اللوحية",
            ],
            "fr": [
                "phénomène sismique",
                "tectonique des plaques",
                "géologie",
                "élasticité des roches",
                "séismes",
                "structure interne du globe",
                "ondes sismiques",
            ],
        },
    },
    "physics": {
        "chemical_kinetics": {
            "ar": [
                "الحركية الكيميائية",
                "سرعة التفاعل",
                "زمن نصف التفاعل",
                "المتابعة الزمنية للتفاعل",
                "العوامل الحركية",
                "التفاعل الكيميائي البطيء",
            ],
            "fr": [
                "cinétique chimique",
                "vitesse de réaction",
                "temps de demi-réaction",
                "suivi temporel d'une transformation",
                "facteurs cinétiques",
                "réaction lente",
            ],
        },
        "mechanical_evolution": {
            "ar": [
                "تطور جملة ميكانيكية",
                "الطاقة الميكانيكية",
                "تأثير الاحتكاك",
                "المتردد الميكانيكي",
                "الحركة المستوية",
            ],
            "fr": [
                "évolution d'un système mécanique",
                "énergie mécanique",
                "frottements",
                "oscillateur mécanique",
                "mouvement plan",
            ],
        },
        "mechanics": {
            "ar": [
                "الميكانيك",
                "قوانين نيوتن",
                "السقوط الحر",
                "الحركة في مجال جاذبية",
                "المرجع العطالي",
                "كمية الحركة",
            ],
            "fr": [
                "mécanique",
                "lois de Newton",
                "chute libre",
                "mouvement dans un champ de gravitation",
                "référentiel galiléen",
                "quantité de mouvement",
            ],
        },
        "rc_rl_circuits": {
            "ar": [
                "ثنائي القطب RC",
                "ثنائي القطب RL",
                "شحن المكثفة",
                "تفريغ المكثفة",
                "الوشيعة",
                "زمن الاستجابة",
                "الدارة الكهربائية",
            ],
            "fr": [
                "dipôle RC",
                "dipôle RL",
                "charge du condensateur",
                "décharge du condensateur",
                "bobine",
                "constante de temps",
                "circuit électrique",
            ],
        },
        "acid_base_equilibrium": {
            "ar": [
                "التوازن الحمض-أساس",
                "التفاعلات الحمضية القاعدية",
                "pH",
                "المعايرة الحمضية القاعدية",
                "ثابت الحموضة",
                "المحاليل المنظمة",
            ],
            "fr": [
                "équilibre acido-basique",
                "réactions acide-base",
                "pH",
                "titrage acido-basique",
                "constante d'acidité",
                "solution tampon",
            ],
        },
        "nuclear": {
            "ar": [
                "التفاعلات النووية",
                "النشاط الإشعاعي",
                "الانشطار النووي",
                "الاندماج النووي",
                "قانون التناقص الإشعاعي",
                "عمر النصف",
            ],
            "fr": [
                "réactions nucléaires",
                "radioactivité",
                "fission nucléaire",
                "fusion nucléaire",
                "loi de décroissance radioactive",
                "demi-vie",
            ],
        },
    },
    "math": {
        "functions": {
            "ar": [
                "الدوال العددية",
                "دراسة الدوال",
                "نهايات الدوال",
                "اشتقاق الدوال",
                "استمرارية الدالة",
                "تغيرات الدالة",
            ],
            "fr": [
                "fonctions numériques",
                "étude de fonctions",
                "limites de fonctions",
                "dérivation",
                "continuité",
                "variations d'une fonction",
            ],
        },
        "exponential_logarithm": {
            "ar": [
                "الدالة الأسية",
                "الدالة اللوغاريتمية",
                "اللوغاريتم النبيري",
                "معادلات أسية",
                "متراجحات لوغاريتمية",
            ],
            "fr": [
                "fonction exponentielle",
                "fonction logarithme",
                "logarithme népérien",
                "équations exponentielles",
                "inéquations logarithmiques",
            ],
        },
        "sequences": {
            "ar": [
                "المتتاليات العددية",
                "متتالية حسابية",
                "متتالية هندسية",
                "نهاية متتالية",
                "الاستدلال بالتراجع",
            ],
            "fr": [
                "suites numériques",
                "suite arithmétique",
                "suite géométrique",
                "limite d'une suite",
                "raisonnement par récurrence",
            ],
        },
        "probability": {
            "ar": [
                "الاحتمالات",
                "المتغير العشوائي",
                "قانون الاحتمال",
                "الاحتمال الشرطي",
                "الاستقلالية الاحتمالية",
            ],
            "fr": [
                "probabilités",
                "variable aléatoire",
                "loi de probabilité",
                "probabilité conditionnelle",
                "indépendance en probabilité",
            ],
        },
        "complex_numbers": {
            "ar": [
                "الأعداد المركبة",
                "الشكل الجبري للعدد المركب",
                "الشكل الأسي",
                "معيار عدد مركب",
                "عمدة عدد مركب",
            ],
            "fr": [
                "nombres complexes",
                "forme algébrique",
                "forme exponentielle",
                "module d'un nombre complexe",
                "argument d'un nombre complexe",
            ],
        },
        "space_geometry": {
            "ar": [
                "الهندسة في الفضاء",
                "المستقيمات والمستويات في الفضاء",
                "الجداء السلمي",
                "تمثيل معلمي",
                "المعادلة الديكارتية للمستوي",
            ],
            "fr": [
                "géométrie dans l'espace",
                "droites et plans de l'espace",
                "produit scalaire",
                "représentation paramétrique",
                "équation cartésienne d'un plan",
            ],
        },
    },
}
