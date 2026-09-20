"""Scope declaration: streams, subjects, pipeline assignment, and syllabus maps.

Stream
------
bac-genius targets a single Algerian Baccalaureate stream:
``experimental_sciences`` (شعبة علوم تجريبية).

Subjects — 7 in scope
---------------------
Three *scientific* subjects run the full pipeline (topic modelling, forecasting,
RAG generation, XAI, evaluation).  Four *language* subjects are ingested for
RAG question-answering only; they do not feed forecasting or generation.

  Subject   coeff  hours  pipeline   folder (data/raw/exams/)  file prefix
  -------   -----  -----  --------   ------------------------  -----------
  svt         6    4.5    full       svt                       bac_svt_
  physic      5    3.5    full       physic                    bac_physic_
  math        5    3.5    full       Math                      bac_math_
  arabe       3    2.5    rag_only   arabe                     bac_arabe_
  islamic     2    2.5    rag_only   Islamic                   bac_islamic_
  francais    2    2.5    rag_only   francais                  bac_francais_
  english     2    2.5    rag_only   english                   bac_english_
                                                               (typo bac_egnlish_
                                                                for 2 files —
                                                                handled by manifest)

``SYLLABUS_MAPS``
-----------------
Bilingual (Arabic / French) keyword lexicon per official syllabus topic.
Used by the ``validation`` package to anchor BERTopic output to the official
programme; NOT the primary topic tagger.  Language-subject maps are intentionally
minimal — they serve RAG retrieval validation only.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Literal

Pipeline = Literal["full", "rag_only"]

# ---------------------------------------------------------------------------
# Streams
# ---------------------------------------------------------------------------

STREAMS: List[str] = ["experimental_sciences"]


# ---------------------------------------------------------------------------
# Subjects
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Subject:
    """One BAC subject in scope."""

    code: str            # internal id, matches filename prefix segment
    folder: str          # exact directory name under data/raw/exams/
    name_ar: str
    name_fr: str
    coefficient: int
    duration_hours: float
    pipeline: Pipeline   # "full" or "rag_only"

    @property
    def file_prefixes(self) -> List[str]:
        """All known filename prefixes for this subject (handles typos)."""
        base = [f"bac_{self.code}_"]
        if self.code == "english":
            base.append("bac_egnlish_")   # 2 mis-named files in data/raw
        return base


SUBJECTS: List[Subject] = [
    # ── Scientific subjects (full pipeline) ───────────────────────────────
    Subject(
        code="svt", folder="svt",
        name_ar="علوم الطبيعة والحياة",
        name_fr="Sciences de la Vie et de la Terre",
        coefficient=6, duration_hours=4.5, pipeline="full",
    ),
    Subject(
        code="physic", folder="physic",
        name_ar="العلوم الفيزيائية",
        name_fr="Sciences Physiques",
        coefficient=5, duration_hours=3.5, pipeline="full",
    ),
    Subject(
        code="math", folder="Math",
        name_ar="الرياضيات",
        name_fr="Mathématiques",
        coefficient=5, duration_hours=3.5, pipeline="full",
    ),
    # ── Language subjects (RAG Q&A only) ──────────────────────────────────
    Subject(
        code="arabe", folder="arabe",
        name_ar="اللغة العربية وآدابها",
        name_fr="Langue et Littérature Arabes",
        coefficient=3, duration_hours=2.5, pipeline="rag_only",
    ),
    Subject(
        code="islamic", folder="Islamic",
        name_ar="العلوم الإسلامية",
        name_fr="Sciences Islamiques",
        coefficient=2, duration_hours=2.5, pipeline="rag_only",
    ),
    Subject(
        code="francais", folder="francais",
        name_ar="اللغة الفرنسية",
        name_fr="Langue Française",
        coefficient=2, duration_hours=2.5, pipeline="rag_only",
    ),
    Subject(
        code="english", folder="english",
        name_ar="اللغة الإنجليزية",
        name_fr="Langue Anglaise",
        coefficient=2, duration_hours=2.5, pipeline="rag_only",
    ),
]

#: Convenience lookups
SUBJECTS_BY_CODE: Dict[str, Subject] = {s.code: s for s in SUBJECTS}
SUBJECTS_BY_FOLDER: Dict[str, Subject] = {s.folder: s for s in SUBJECTS}
FULL_PIPELINE_SUBJECTS: List[Subject] = [s for s in SUBJECTS if s.pipeline == "full"]
RAG_ONLY_SUBJECTS: List[Subject] = [s for s in SUBJECTS if s.pipeline == "rag_only"]


# ---------------------------------------------------------------------------
# Syllabus validation reference
# ---------------------------------------------------------------------------

SyllabusMap = Dict[str, Dict[str, Dict[str, List[str]]]]

SYLLABUS_MAPS: SyllabusMap = {

    # ── SVT ───────────────────────────────────────────────────────────────
    "svt": {
        "protein_function_enzymes_immunity": {
            "ar": [
                "العلاقة بين البنية والوظيفة في البروتين",
                "الإنزيمات", "الحركية الإنزيمية", "الخاصية الفراغية للإنزيم",
                "المناعة", "المناعة الذاتية", "الاستجابة المناعية",
                "الأجسام المضادة", "المعقد المناعي", "الجهاز المناعي",
                "زرع الأعضاء", "فيروس نقص المناعة البشرية",
            ],
            "fr": [
                "relation structure-fonction des protéines", "enzymes",
                "cinétique enzymatique", "spécificité enzymatique",
                "immunité", "réaction immunitaire", "anticorps",
                "complexe immun", "système immunitaire",
                "greffe et rejet", "VIH", "auto-immunité",
            ],
        },
        "neural_communication": {
            "ar": [
                "التواصل العصبي", "العصبون", "المشبك العصبي",
                "الرسالة العصبية", "كمون الراحة", "كمون العمل",
                "الناقل العصبي", "المستقبلات الحسية", "الجملة العصبية",
            ],
            "fr": [
                "communication nerveuse", "neurone", "synapse",
                "message nerveux", "potentiel de repos", "potentiel d'action",
                "neurotransmetteur", "récepteur sensoriel", "système nerveux",
            ],
        },
        "energy_conversion_photosynthesis_mitochondria": {
            "ar": [
                "التحويل الطاقوي", "التركيب الضوئي", "الميتوكوندري",
                "الفسفرة التأكسدية", "سلسلة نقل الإلكترون",
                "الأكسدة التنفسية", "الكلوروبلاست", "ATP", "دورة كالفن",
            ],
            "fr": [
                "conversion d'énergie", "photosynthèse", "mitochondrie",
                "phosphorylation oxydative", "chaîne respiratoire",
                "chloroplaste", "ATP", "cycle de Calvin", "respiration cellulaire",
            ],
        },
        "genetics_heredity": {
            "ar": [
                "الوراثة", "التعبير الجيني", "الطفرة الجينية",
                "الصبغيات", "الانقسام المنصف", "التكاثر الجنسي",
                "قوانين مندل", "الجين", "الحمض النووي DNA",
            ],
            "fr": [
                "génétique", "hérédité", "expression génique",
                "mutation génique", "chromosomes", "méiose",
                "reproduction sexuée", "lois de Mendel", "gène", "ADN",
            ],
        },
        "geology": {
            "ar": [
                "الظاهرة الزلزالية", "الصفائح التكتونية", "الجيولوجيا",
                "المطاطية الصخرية", "الزلازل", "بنية الأرض الداخلية",
                "التكتونية اللوحية",
            ],
            "fr": [
                "phénomène sismique", "tectonique des plaques", "géologie",
                "élasticité des roches", "séismes",
                "structure interne du globe", "ondes sismiques",
            ],
        },
    },

    # ── Physics ───────────────────────────────────────────────────────────
    "physic": {
        "chemical_kinetics": {
            "ar": [
                "الحركية الكيميائية", "سرعة التفاعل", "زمن نصف التفاعل",
                "المتابعة الزمنية للتفاعل", "العوامل الحركية",
                "التفاعل الكيميائي البطيء",
            ],
            "fr": [
                "cinétique chimique", "vitesse de réaction",
                "temps de demi-réaction",
                "suivi temporel d'une transformation",
                "facteurs cinétiques", "réaction lente",
            ],
        },
        "mechanical_evolution": {
            "ar": [
                "تطور جملة ميكانيكية", "الطاقة الميكانيكية",
                "تأثير الاحتكاك", "المتردد الميكانيكي", "الحركة المستوية",
            ],
            "fr": [
                "évolution d'un système mécanique", "énergie mécanique",
                "frottements", "oscillateur mécanique", "mouvement plan",
            ],
        },
        "mechanics": {
            "ar": [
                "الميكانيك", "قوانين نيوتن", "السقوط الحر",
                "الحركة في مجال جاذبية", "المرجع العطالي", "كمية الحركة",
            ],
            "fr": [
                "mécanique", "lois de Newton", "chute libre",
                "mouvement dans un champ de gravitation",
                "référentiel galiléen", "quantité de mouvement",
            ],
        },
        "rc_rl_circuits": {
            "ar": [
                "ثنائي القطب RC", "ثنائي القطب RL",
                "شحن المكثفة", "تفريغ المكثفة", "الوشيعة",
                "زمن الاستجابة", "الدارة الكهربائية",
            ],
            "fr": [
                "dipôle RC", "dipôle RL",
                "charge du condensateur", "décharge du condensateur",
                "bobine", "constante de temps", "circuit électrique",
            ],
        },
        "acid_base_equilibrium": {
            "ar": [
                "التوازن الحمض-أساس", "التفاعلات الحمضية القاعدية",
                "pH", "المعايرة الحمضية القاعدية",
                "ثابت الحموضة", "المحاليل المنظمة",
            ],
            "fr": [
                "équilibre acido-basique", "réactions acide-base", "pH",
                "titrage acido-basique", "constante d'acidité", "solution tampon",
            ],
        },
        "nuclear": {
            "ar": [
                "التفاعلات النووية", "النشاط الإشعاعي",
                "الانشطار النووي", "الاندماج النووي",
                "قانون التناقص الإشعاعي", "عمر النصف",
            ],
            "fr": [
                "réactions nucléaires", "radioactivité",
                "fission nucléaire", "fusion nucléaire",
                "loi de décroissance radioactive", "demi-vie",
            ],
        },
        "waves_optics": {
            "ar": [
                "الموجات", "الضوء", "الانكسار", "الانعكاس",
                "الحيود", "التداخل", "الموجة الميكانيكية",
            ],
            "fr": [
                "ondes", "lumière", "réfraction", "réflexion",
                "diffraction", "interférences", "onde mécanique",
            ],
        },
    },

    # ── Math ──────────────────────────────────────────────────────────────
    "math": {
        "functions": {
            "ar": [
                "الدوال العددية", "دراسة الدوال", "نهايات الدوال",
                "اشتقاق الدوال", "استمرارية الدالة", "تغيرات الدالة",
            ],
            "fr": [
                "fonctions numériques", "étude de fonctions",
                "limites de fonctions", "dérivation",
                "continuité", "variations d'une fonction",
            ],
        },
        "exponential_logarithm": {
            "ar": [
                "الدالة الأسية", "الدالة اللوغاريتمية",
                "اللوغاريتم النبيري", "معادلات أسية", "متراجحات لوغاريتمية",
            ],
            "fr": [
                "fonction exponentielle", "fonction logarithme",
                "logarithme népérien", "équations exponentielles",
                "inéquations logarithmiques",
            ],
        },
        "sequences": {
            "ar": [
                "المتتاليات العددية", "متتالية حسابية", "متتالية هندسية",
                "نهاية متتالية", "الاستدلال بالتراجع",
            ],
            "fr": [
                "suites numériques", "suite arithmétique", "suite géométrique",
                "limite d'une suite", "raisonnement par récurrence",
            ],
        },
        "integrals": {
            "ar": [
                "التكامل", "الحساب التكاملي", "التكامل المحدود",
                "المساحة", "الدالة الأصلية",
            ],
            "fr": [
                "intégration", "calcul intégral", "intégrale définie",
                "aire", "primitive",
            ],
        },
        "probability": {
            "ar": [
                "الاحتمالات", "المتغير العشوائي", "قانون الاحتمال",
                "الاحتمال الشرطي", "الاستقلالية الاحتمالية",
            ],
            "fr": [
                "probabilités", "variable aléatoire", "loi de probabilité",
                "probabilité conditionnelle", "indépendance en probabilité",
            ],
        },
        "complex_numbers": {
            "ar": [
                "الأعداد المركبة", "الشكل الجبري للعدد المركب",
                "الشكل الأسي", "معيار عدد مركب", "عمدة عدد مركب",
            ],
            "fr": [
                "nombres complexes", "forme algébrique", "forme exponentielle",
                "module d'un nombre complexe", "argument d'un nombre complexe",
            ],
        },
        "space_geometry": {
            "ar": [
                "الهندسة في الفضاء", "المستقيمات والمستويات في الفضاء",
                "الجداء السلمي", "تمثيل معلمي",
                "المعادلة الديكارتية للمستوي",
            ],
            "fr": [
                "géométrie dans l'espace", "droites et plans de l'espace",
                "produit scalaire", "représentation paramétrique",
                "équation cartésienne d'un plan",
            ],
        },
        "differential_equations": {
            "ar": [
                "المعادلات التفاضلية", "المعادلة التفاضلية من الرتبة الأولى",
            ],
            "fr": [
                "équations différentielles",
                "équation différentielle du premier ordre",
            ],
        },
    },

    # ── Language subjects — minimal RAG validation anchors ─────────────────
    "arabe": {
        "comprehension_expression": {
            "ar": ["فهم المقروء", "التعبير الكتابي", "النص الأدبي", "التحليل الأدبي"],
            "fr": ["compréhension écrite", "expression écrite", "texte littéraire"],
        },
        "grammar_rhetoric": {
            "ar": ["النحو", "الصرف", "البلاغة", "التراكيب اللغوية"],
            "fr": ["grammaire arabe", "rhétorique", "morphologie"],
        },
    },
    "islamic": {
        "quran_hadith": {
            "ar": ["القرآن الكريم", "الحديث النبوي", "التفسير", "علوم القرآن"],
            "fr": ["Coran", "Hadith", "exégèse coranique"],
        },
        "fiqh_aqeedah": {
            "ar": ["الفقه الإسلامي", "العقيدة", "السيرة النبوية", "الأخلاق الإسلامية"],
            "fr": ["jurisprudence islamique", "théologie", "biographie prophétique"],
        },
    },
    "francais": {
        "comprehension_expression": {
            "ar": ["فهم النص", "التعبير الكتابي بالفرنسية"],
            "fr": [
                "compréhension de texte", "expression écrite",
                "texte argumentatif", "résumé", "compte rendu",
            ],
        },
        "grammar_vocabulary": {
            "ar": ["قواعد اللغة الفرنسية", "المفردات"],
            "fr": ["grammaire française", "vocabulaire", "syntaxe", "conjugaison"],
        },
    },
    "english": {
        "comprehension_expression": {
            "ar": ["فهم النص الإنجليزي", "التعبير بالإنجليزية"],
            "fr": ["reading comprehension", "written expression"],
            "en": [
                "reading comprehension", "written expression",
                "essay writing", "summary", "text analysis",
            ],
        },
        "grammar_vocabulary": {
            "ar": ["قواعد اللغة الإنجليزية"],
            "fr": ["grammaire anglaise", "vocabulaire anglais"],
            "en": ["grammar", "vocabulary", "tenses", "conditionals"],
        },
    },
}
