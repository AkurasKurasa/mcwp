"""Reference data and the feature schema the models are trained on.

Only things an engineer can actually state at bid time appear as features:
project type, the materials list, budget, size, location and duration.
Everything else that drives waste in the real world - crew quality, storage,
design churn - is deliberately left unobserved, and shows up as uncertainty.
"""

from dataclasses import dataclass, asdict


@dataclass(frozen=True)
class Material:
    key: str
    name: str
    category: str
    unit: str
    unit_cost: float          # currency per unit, before the regional index
    mass_kg_per_unit: float
    co2e_kg_per_unit: float
    base_waste: float         # industry baseline waste fraction
    recycle_rate: float       # fraction of offcuts typically diverted
    fragility: float          # 0-1, damage sensitivity in transit and handling
    volatility: float         # unit-price dispersion, drives overrun risk
    lead_time_days: int
    accent: str

    def as_dict(self):
        return asdict(self)


MATERIALS = [
    Material("ready_mix_concrete", "Ready-Mix Concrete", "Structural", "m³",
             148.0, 2400.0, 264.0, 0.055, 0.32, 0.15, 0.07, 3, "var(--tone-1)"),
    Material("rebar_steel", "Reinforcing Steel", "Structural", "tonne",
             985.0, 1000.0, 1850.0, 0.038, 0.93, 0.10, 0.14, 21, "var(--tone-2)"),
    Material("structural_steel", "Structural Steel", "Structural", "tonne",
             1465.0, 1000.0, 1920.0, 0.026, 0.96, 0.12, 0.16, 45, "var(--tone-3)"),
    Material("dimensional_lumber", "Dimensional Lumber", "Carpentry", "m³",
             624.0, 510.0, 128.0, 0.102, 0.54, 0.35, 0.19, 10, "var(--tone-4)"),
    Material("plywood_sheathing", "Plywood Sheathing", "Carpentry", "sheet",
             47.5, 21.0, 22.4, 0.094, 0.46, 0.40, 0.17, 12, "var(--tone-5)"),
    Material("gypsum_drywall", "Gypsum Wallboard", "Interior", "sheet",
             16.4, 24.0, 9.6, 0.132, 0.24, 0.72, 0.08, 7, "var(--tone-1)"),
    Material("clay_brick", "Clay Brick", "Envelope", "1000 units",
             782.0, 2600.0, 486.0, 0.071, 0.41, 0.30, 0.06, 25, "var(--tone-2)"),
    Material("cmu_block", "Concrete Masonry Unit", "Envelope", "unit",
             3.15, 17.0, 3.4, 0.062, 0.44, 0.22, 0.05, 14, "var(--tone-3)"),
    Material("glazing_unit", "Insulated Glazing Unit", "Envelope", "m²",
             312.0, 26.0, 96.0, 0.044, 0.18, 0.88, 0.12, 56, "var(--tone-4)"),
    Material("mineral_wool", "Mineral Wool Insulation", "Envelope", "m²",
             14.6, 4.2, 5.6, 0.118, 0.14, 0.55, 0.09, 9, "var(--tone-5)"),
    Material("membrane_roofing", "TPO Roofing Membrane", "Envelope", "m²",
             38.5, 2.1, 12.8, 0.086, 0.11, 0.28, 0.11, 18, "var(--tone-1)"),
    Material("ceramic_tile", "Porcelain Tile", "Finishes", "m²",
             43.0, 22.0, 16.2, 0.124, 0.06, 0.78, 0.10, 30, "var(--tone-2)"),
    Material("interior_paint", "Interior Paint", "Finishes", "L",
             9.9, 1.3, 3.2, 0.141, 0.03, 0.20, 0.07, 5, "var(--tone-3)"),
    Material("copper_piping", "Copper Piping", "MEP", "m",
             26.4, 1.4, 8.6, 0.052, 0.91, 0.18, 0.24, 20, "var(--tone-4)"),
    Material("electrical_conduit", "Electrical Conduit", "MEP", "m",
             7.4, 1.1, 2.7, 0.078, 0.62, 0.24, 0.13, 11, "var(--tone-5)"),
    Material("asphalt_mix", "Hot-Mix Asphalt", "Sitework", "tonne",
             118.0, 1000.0, 54.0, 0.041, 0.82, 0.08, 0.15, 4, "var(--tone-1)"),
]

MATERIAL_INDEX = {m.key: m for m in MATERIALS}
MATERIAL_CATEGORIES = sorted({m.category for m in MATERIALS})

# Typical quantity of each material on a 1,000 m2 job, used to propose
# sensible starting quantities and to scale the synthetic corpus.
QUANTITY_PER_1000M2 = {
    "ready_mix_concrete": 310,
    "rebar_steel": 28,
    "structural_steel": 44,
    "dimensional_lumber": 62,
    "plywood_sheathing": 700,
    "gypsum_drywall": 1250,
    "clay_brick": 20,
    "cmu_block": 4200,
    "glazing_unit": 190,
    "mineral_wool": 1500,
    "membrane_roofing": 620,
    "ceramic_tile": 550,
    "interior_paint": 450,
    "copper_piping": 1000,
    "electrical_conduit": 2500,
    "asphalt_mix": 290,
}


@dataclass(frozen=True)
class ProjectType:
    key: str
    name: str
    family: str               # Residential / Commercial / Other
    waste_multiplier: float
    overrun_bias: float       # structural tendency to blow the budget
    typical_area: int


PROJECT_TYPES = [
    ProjectType("res_single", "Residential - Single Family", "Residential", 1.08, 0.10, 260),
    ProjectType("res_multi", "Residential - Multi-Family", "Residential", 0.98, 0.04, 8200),
    ProjectType("com_office", "Commercial - Office", "Commercial", 0.94, -0.02, 9200),
    ProjectType("com_retail", "Commercial - Retail / Fit-Out", "Commercial", 1.15, 0.14, 1400),
    ProjectType("com_hospitality", "Commercial - Hospitality", "Commercial", 1.06, 0.09, 5400),
    ProjectType("com_industrial", "Commercial - Industrial", "Commercial", 0.88, -0.08, 18000),
    ProjectType("institutional", "Institutional - Health / Education", "Other", 1.04, 0.12, 11000),
    ProjectType("civil", "Civil / Infrastructure", "Other", 0.91, 0.06, 26000),
    ProjectType("renovation", "Renovation / Refurbishment", "Other", 1.30, 0.22, 1900),
]
PROJECT_TYPE_INDEX = {p.key: p for p in PROJECT_TYPES}


@dataclass(frozen=True)
class Region:
    key: str
    name: str
    cost_index: float     # multiplier on material unit cost
    labor_index: float
    volatility: float     # regional price dispersion


REGIONS = [
    Region("ne_metro", "Northeast Metro", 1.19, 1.31, 0.085),
    Region("mid_atlantic", "Mid-Atlantic", 1.07, 1.12, 0.062),
    Region("southeast", "Southeast", 0.93, 0.88, 0.051),
    Region("midwest", "Midwest", 0.97, 0.96, 0.048),
    Region("gulf", "Gulf Coast", 0.95, 0.94, 0.074),
    Region("mountain", "Mountain West", 1.03, 1.01, 0.057),
    Region("pacific_nw", "Pacific Northwest", 1.11, 1.18, 0.066),
    Region("west_coast", "West Coast Metro", 1.24, 1.38, 0.091),
]
REGION_INDEX = {r.key: r for r in REGIONS}


# --------------------------------------------------------------- feature sets

# Per material line. Everything here is derivable from the engineer's inputs.
LINE_FEATURES = [
    "material", "project_type", "region",
    "quantity_log", "project_area_log", "duration_weeks",
    "line_count", "line_value_share", "budget_ratio", "schedule_intensity",
    "storage_ratio", "rain_days", "experience_years",
]

LINE_CATEGORICALS = ["material", "project_type", "region"]

# Per project, for the cost-overrun classifier. `expected_waste` is stacked
# from the waste model, so the classifier sees what the regressor concluded.
PROJECT_FEATURES = [
    "project_type", "region",
    "project_area_log", "duration_weeks", "line_count",
    "budget_ratio", "budget_per_m2", "schedule_intensity",
    "expected_waste", "mix_concentration", "fragile_share", "volatility_weighted",
    "storage_ratio", "rain_days", "experience_years",
]

PROJECT_CATEGORICALS = ["project_type", "region"]

CATEGORY_LEVELS = {
    "material": [m.key for m in MATERIALS],
    "project_type": [p.key for p in PROJECT_TYPES],
    "region": [r.key for r in REGIONS],
}

FEATURE_LABELS = {
    "material": "Material",
    "project_type": "Project Type",
    "region": "Location",
    "quantity_log": "Order Size",
    "project_area_log": "Project Size",
    "duration_weeks": "Duration",
    "line_count": "Materials in Package",
    "line_value_share": "Share of Package Value",
    "budget_ratio": "Budget vs Benchmark",
    "schedule_intensity": "Build Rate (m²/week)",
    "budget_per_m2": "Budget per m²",
    "expected_waste": "Forecast Waste",
    "mix_concentration": "Mix Concentration",
    "fragile_share": "Fragile Material Share",
    "volatility_weighted": "Price Volatility Exposure",
    "storage_ratio": "Storage Adequacy",
    "storage_m2": "Storage Size",
    "rain_days": "Rain Frequency",
    "experience_years": "Contractor Experience",
}
