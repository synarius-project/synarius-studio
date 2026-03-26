project = "synarius-studio"
extensions = ["sphinx_needs"]

needs_types = [
    {"directive": "need", "title": "Requirement", "prefix": "NEED_", "color": "#E8DAEF", "style": "node"},
    {"directive": "sys", "title": "System Requirement", "prefix": "SYS_", "color": "#BFD8D2", "style": "node"},
    {"directive": "arch", "title": "Architecture Requirement", "prefix": "ARCH_", "color": "#F2D7D5", "style": "node"},
    {"directive": "comp", "title": "Component Requirement", "prefix": "COMP_", "color": "#D6EAF8", "style": "node"},
]

needs_id_regex = "^[A-Z0-9-]{5,}$"

