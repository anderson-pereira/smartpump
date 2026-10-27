from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECIPE_DIRECTORY = PROJECT_ROOT / "recipes"


VALVE_SERIAL_PORT = "COM22"
VALVE_BAUD_RATE = 9600
VALVE_ADDRESS = "1"
VALVE_CHANNEL_COUNT = 6


FLOW_PUMP_SERIAL_PORT = "COM21"
FLOW_PUMP_BAUD_RATE = 9600
FLOW_PUMP_ADDRESS = 1
FLOW_PUMP_STOP_DELAY_SECONDS = 0.3
FLOW_PUMP_RESTART_DELAY_SECONDS = 0.3


# RECIPE = [
#     (1, "Ethanol 5%",   5),
#     (2, "Ethanol 10%",  5),
# ]


# RECIPE = [
#     (3, "PBS",  3),
#     (6, "H2O",  3),
# ]



RECIPE = [
    (2, "PBS",                  5),
    (1, "Biotina",              15),
    (2, "PBS",                  20),
    (3, "C2: 6.66nM Neut.",     3),
    (2, "PBS",                  3),
    (4, "C3: 33.33nM Neut.",    3),
    (2, "PBS",                  3),
    (5, "C4: 166.67nM Neut.",   3),
    (2, "PBS",                  3),
    (6, "C5: 833.33nM Neut.",   3),
    (2, "PBS",                  10),
]


# RECIPE = [
#     (1, "Ethanol 5%",   1),
#     (3, "H2O",          1),
#     (2, "Ethanol 10%",  1),
#     (3, "H2O",          1),
#     (4, "Ethanol 15%",  1),
#     (3, "H2O",          1),
#     (5, "Ethanol 20%",  1),
#     (3, "H2O",          1),
# ]


# RECIPE = [
#     # (1, "H2O",          0.02),
#     (1, "H2O",          0.02),
#     (2, "Ethanol 5%",   0.02),
#     (1, "H2O",          0.02),
#     (3, "Ethanol 10%",  0.02),
#     (1, "H2O",          0.02),
#     (4, "Ethanol 15%",  0.02),
#     (1, "H2O",          0.02),
#     (5, "Ethanol 20%",  0.02),
#     # (1, "H2O",          0),
# ]


# RECIPE = [
#     (1, "01",  0.25),
#     (2, "02",  0.25),
#     (3, "03",  0.25),
#     (4, "04",  0.25),
#     (5, "05",  0.25),
#     (6, "06",  0.25),
#     (5, "05",  0.25),
#     (4, "04",  0.25),
#     (3, "03",  0.25),
#     (2, "02",  0.25),
# ]


# RECIPE = [
#     (1, "01",  0.25),
#     (2, "02",  0.25),
#     (3, "03",  0.25),
#     (4, "04",  0.25),
#     (5, "05",  0.25),
#     (6, "06",  0.25),
# ]


# RECIPE = [
#     (1, "H2O",              4),
#     (3, "PBS",              5),
#     (2, "Biotina",          5),
#     (3, "PBS",              5),
#     (4, "Neutravidina",     10),
#     (3, "PBS",              10),
# ]
