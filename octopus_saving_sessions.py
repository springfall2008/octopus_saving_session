# -*- coding: utf-8 -*-
"""Used to calculate payback for Octopus saving sessions
Original author unknown
"""

import numpy as np
import pandas as pd
import requests
#!pip install -q pendulum # better date time support
import pendulum

# Your Octopus API Key (eg "sk_live_...")
# Find this in your online dashboard: https://octopus.energy/dashboard/developer/ 
# DON'T SHARE THIS!
API_KEY = "sk_live_xxxxxxxxxxxxxxxx"
# Find this on an electricity bill - it's the 13 digit number next to the box marked 'Supply number S' (eg "1234567890123")
MPAN = "1234567890123"
# Find this on an electricity bill after "Energy Charges for Meter xxx" (eg "12P3845959")
SERIAL_NUMBER = "12P3845959"
# Set these to your unit rates (and set the sessions below)
UNIT_RATE = 42
LOW_RATE = 10

# timestamp, session length (half hours), points awarded per kwh saved, history days offset, the rate during the in day adjustment, the rate you could have used instead
saving_sessions = [
    ('2023-03-23 18:30', 2, 2400, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-03-15 18:30', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-02-21 17:30', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-02-13 17:30', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-01-30 09:00', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-01-24 16:30', 3, 3200, 0, UNIT_RATE, LOW_RATE), # 1.5h
    ('2023-01-23 17:00', 2, 2700, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2023-01-19 09:00', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2022-12-12 17:00', 4, 1800, 0, UNIT_RATE, LOW_RATE), # 2h
    ('2022-12-01 17:00', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2022-11-30 17:30', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2022-11-22 17:30', 2, 1800, 0, UNIT_RATE, LOW_RATE), # 1h
    ('2022-11-15 17:00', 2, 1800, 0, UNIT_RATE, LOW_RATE) # 1h
]

# get historic readings
url = f"https://api.octopus.energy/v1/electricity-meter-points/{MPAN}/meters/{SERIAL_NUMBER}/consumption/?page_size=20000"
results = []
START = pendulum.datetime(2022, 11, 1)
while True:
    resp = requests.get(url, auth=(API_KEY, ''))
    resp.raise_for_status()
    page = []
    for row in resp.json()["results"]:
        ivt = (pendulum.parse(row["interval_start"]))
        page.append( 
           {"interval_start": ivt, "interval_start_date": ivt.date(), "interval_start_time": ivt.time(), "consumption": row["consumption"]}
        )
    results.extend(page)
    if results[-1]["interval_start"] < START:
        break
    url = resp.json()["next"]

df = pd.DataFrame(results).set_index("interval_start")
df_date = pd.DataFrame(results).set_index("interval_start_date")
df_time = pd.DataFrame(results).set_index("interval_start_time")

HH = pendulum.duration(minutes=30)
POINTS_PER_KWH = 800

def weekday(day):
    """True if day is a weekday"""
    return pendulum.MONDAY <= day.day_of_week <= pendulum.FRIDAY

def calculate(session, length, points_per_kwh, history_offset, rate, shifted_rate):
    session = pendulum.parse(session)
    """Calculate points earned per session"""
    ida_times = [session.time() - HH*i for i in range(3, 9)]
    saving_times = [session.time() + HH*i for i in range(length)]
    previous_session_days = {pendulum.parse(d).date() for d, *_ in saving_sessions}
    # draw history from previous 10 matching weekdays not in a previous session
    history = []
    for i in range(history_offset+1, 100):
        day = session - pendulum.duration(days=i)
        if weekday(session) == weekday(day) and day.date() not in previous_session_days:
            history.append(day.date())
        if len(history) == 10:
            break

    c = df.consumption
    c_date = df_date.consumption
    c_time = df_time.consumption

    baseline = c[np.isin(c_date.index, history)]
    baseline_time = c_time[np.isin(c_date.index, history)]
    actual = c[c_date.index == session.date()]
    actual_time = c_time[c_date.index == session.date()]

    # calculate in day adjustment
    baseline_ida = baseline[np.isin(baseline_time.index, ida_times)].mean()
    actual_ida = actual[np.isin(actual_time.index, ida_times)].mean()
    ida  = actual_ida - baseline_ida

    # calculate usage per HH slot
    baseline_usage = baseline[np.isin(baseline_time.index, saving_times)]
    baseline_usage_time = baseline_time[np.isin(baseline_time.index, saving_times)]
    baseline_usage = baseline_usage.groupby(baseline_usage_time.index).mean()

    actual_usage = actual[np.isin(actual_time.index, saving_times)]
    actual_usage_time = actual_time[np.isin(actual_time.index, saving_times)]
    actual_usage = actual_usage.groupby(actual_usage_time.index).mean()

    # saving is calculated per settlement period (half hour), and only positives savings considered
    kwh = (baseline_usage - actual_usage + ida).clip(lower=0)
    points = kwh.sum() * points_per_kwh
    result = (np.ceil(points / 8) * 8).astype(int)
    cost = rate * actual_ida * 6 / 100
    shifted_cost = shifted_rate * actual_ida * 6 / 100
    payback = result / POINTS_PER_KWH
    retd = {
        "session": session,
        "baseline_adjust" : baseline_ida,
        "day_adjust" : round(actual_ida, 2),
        "ida" : round(ida, 2),
        "points": result,
        "payback": payback,
        "cost": round(cost, 2),
        "shifted_cost": round(shifted_cost, 2),
        "profit": round(payback-cost+shifted_cost, 2),
    }
    print(retd)
    return retd

pd.DataFrame(calculate(*row) for row in saving_sessions).set_index("session")
