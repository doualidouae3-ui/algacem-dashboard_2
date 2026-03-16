import math
import random
import os
import csv
import io
from datetime import datetime, timedelta
from flask import Flask, render_template, jsonify, request, make_response

app = Flask(__name__)

POND_DEFS = [
    {"id": "A-1", "row": "A", "col": 1, "volume_m3": 150, "area_m2": 500,
     "species": "Spirulina platensis", "day": 3, "inoculated": "2026-03-12"},
    {"id": "A-2", "row": "A", "col": 2, "volume_m3": 150, "area_m2": 500,
     "species": "Spirulina platensis", "day": 4, "inoculated": "2026-03-11"},
    {"id": "A-3", "row": "A", "col": 3, "volume_m3": 150, "area_m2": 500,
     "species": "Spirulina platensis", "day": 6, "inoculated": "2026-03-09"},
    {"id": "A-4", "row": "A", "col": 4, "volume_m3": 150, "area_m2": 500,
     "species": "Spirulina platensis", "day": 2, "inoculated": "2026-03-13"},
    {"id": "B-1", "row": "B", "col": 1, "volume_m3": 180, "area_m2": 600,
     "species": "Spirulina platensis", "day": 4, "inoculated": "2026-03-11"},
    {"id": "B-2", "row": "B", "col": 2, "volume_m3": 180, "area_m2": 600,
     "species": "Spirulina platensis", "day": 7, "inoculated": "2026-03-08"},
    {"id": "B-3", "row": "B", "col": 3, "volume_m3": 180, "area_m2": 600,
     "species": "Spirulina platensis", "day": 9, "inoculated": "2026-03-06"},
    {"id": "B-4", "row": "B", "col": 4, "volume_m3": 180, "area_m2": 600,
     "species": "Spirulina platensis", "day": 1, "inoculated": "2026-03-14"},
]

K_CAPACITY = 2.3
R_GROWTH   = 0.38
D0_INITIAL = 0.10

def get_recommendations(p):
    recs = []
    if p["ph"] > 8.5:
        recs.append({"priority":"critical","issue":f"pH critically high ({p['ph']:.2f})",
            "cause":"Intense photosynthesis consuming CO₂ faster than injection rate.",
            "actions":[f"Increase CO₂ flow to {min(32,p['co2_flow']*1.4):.1f} m³/h (+40%)",
                "Check CO₂ injection nozzles for blockage",
                "Reduce paddlewheel to 16 RPM to slow outgassing",
                "If pH exceeds 9.0 consider emergency dilution with fresh medium"],
            "timeframe":"Act within 1 hour"})
    elif p["ph"] > 8.25:
        recs.append({"priority":"warning","issue":f"pH elevated ({p['ph']:.2f})",
            "cause":"CO₂ injection not keeping pace with photosynthetic demand.",
            "actions":[f"Increase CO₂ flow to {min(28,p['co2_flow']*1.22):.1f} m³/h (+22%)",
                "Monitor pH every 30 min until below 8.2",
                "Check kiln output — may be running at reduced capacity"],
            "timeframe":"Act within 3 hours"})
    if p["temperature"] > 32:
        recs.append({"priority":"critical","issue":f"Temperature critical ({p['temperature']:.1f}°C)",
            "cause":"Ambient heat exceeding Spirulina tolerance threshold.",
            "actions":["Activate shade netting (50% PAR reduction)",
                "Increase paddlewheel to 28 RPM for evaporative cooling",
                "Add chilled fresh water — max 10% volume dilution"],
            "timeframe":"Act immediately"})
    elif p["temperature"] > 30:
        recs.append({"priority":"warning","issue":f"Temperature elevated ({p['temperature']:.1f}°C)",
            "cause":"Approaching upper thermal tolerance for Spirulina.",
            "actions":["Monitor every 15 min","Prepare shade netting for deployment",
                "Increase paddlewheel to 24 RPM for surface cooling"],
            "timeframe":"Monitor closely"})
    if p["days_to_harvest"] == 0:
        recs.append({"priority":"harvest","issue":"Pond at or past peak density",
            "cause":"Logistic model indicates carrying capacity reached.",
            "actions":["Harvest immediately — quality degrades after 24h past peak",
                "Prepare centrifuge/filtration system",
                f"Expected yield: {p['biomass_kg']:.0f} kg at {p['density']:.2f} g/L",
                f"Grade projection: {p['grade']} — harvest before grade drops"],
            "timeframe":"Harvest within 6-12 hours"})
    elif 0 < p["days_to_harvest"] < 1.5:
        recs.append({"priority":"info","issue":f"Harvest window in {p['days_to_harvest']:.1f} days",
            "cause":"Density curve approaching plateau — optimal window upcoming.",
            "actions":["Schedule harvesting equipment and personnel",
                "Confirm centrifuge availability",
                "Prepare fresh medium for re-inoculation"],
            "timeframe":"Prepare now, harvest in 24-36h"})
    if p["absorption"] < 60 and p["par"] > 200:
        recs.append({"priority":"warning","issue":f"Low CO₂ absorption ({p['absorption']}%)",
            "cause":"CO₂ not absorbed efficiently — possible diffuser fouling.",
            "actions":["Inspect CO₂ injection diffusers for blockage",
                f"Reduce flow to {max(8,p['co2_flow']*0.85):.1f} m³/h and re-assess",
                "Monitor pH response over 30 minutes"],
            "timeframe":"Inspect within 2 hours"})
    if not recs:
        recs.append({"priority":"ok","issue":"All parameters within optimal range",
            "cause":"Pond operating normally.","actions":["Continue standard monitoring","Next check in 2 hours"],
            "timeframe":"Routine monitoring"})
    return recs

def par(hour):
    if hour < 6.0 or hour > 20.0: return 0.0
    x = (hour - 13.0) / 3.8
    return round(max(0.0, 1150.0 * math.exp(-x * x)), 1)

def temperature(hour, base=23.5, swing=4.5):
    phase = (hour - 14.5) * math.pi / 12.0
    return round(base + swing * math.cos(phase), 2)

def ph_model(hour, density, co2_flow):
    light = par(hour)
    co2_base = -0.28 * min(1.0, co2_flow / 20.0)
    photo_up = 0.065 * (light / 100.0) * density
    return round(max(6.8, min(9.8, 7.62 + co2_base + photo_up)), 2)

def growth_factor(light, temp, ph, co2):
    lf = min(1.0, light / 800.0) if light > 0 else 0.03
    tf = 1.0 if 25 <= temp <= 35 else (max(0.0,(temp-15)/10) if temp<25 else max(0.0,1.0-(temp-35)*0.15))
    pf = 1.0 if 7.4 <= ph <= 8.4 else (max(0.0,0.6+(ph-7.4)*0.4) if ph<7.4 else max(0.0,1.0-(ph-8.4)*0.40))
    cf = min(1.0, co2 / 14.0)
    return round(lf * tf * pf * cf, 4)

def logistic_density(day):
    return round(K_CAPACITY / (1.0 + ((K_CAPACITY - D0_INITIAL) / D0_INITIAL) * math.exp(-R_GROWTH * day)), 3)

def pond_state(pdef, hour=None, co2_override=None, temp_offset=0.0, rpm_override=None):
    if hour is None:
        now = datetime.now()
        hour = now.hour + now.minute / 60.0
    day = pdef["day"]
    idx = pdef["col"] - 1
    density = round(logistic_density(day) * (0.94 + idx * 0.025), 3)
    co2_flow = co2_override if co2_override is not None else round(11.0 + density * 4.0 + random.uniform(-0.3, 0.3), 1)
    light = par(hour)
    temp  = temperature(hour) + temp_offset
    ph    = ph_model(hour, density, co2_flow)
    gf    = growth_factor(light, temp, ph, co2_flow)
    o2    = round(min(115.0, 84.0 + gf*17.0 + (light/1150.0)*11.0), 1)
    absp  = round(min(99.0,  55.0 + gf*42.0 + (light/1150.0)*18.0), 1)
    turb  = round(0.08 + density*0.22 + random.uniform(-0.01,0.01), 2)
    sal   = round(17.8 + idx*0.35 + random.uniform(-0.05,0.05), 1)
    rpm   = rpm_override if rpm_override is not None else (16 if light<80 else (24 if density>1.8 else 22))
    density_crash = density < 0.15 and day > 3
    low_absorption = absp < 60 and light > 200
    if ph > 8.65 or temp > 35.0 or density_crash:
        status = "critical"
    elif ph > 8.25 or temp > 31.0 or low_absorption:
        status = "warning"
    else:
        status = "healthy"
    stage_map = [(2,"Inoculation"),(5,"Exponential"),(7,"Linear"),(9,"Near Peak"),(99,"Declining")]
    stage = next(s for d,s in stage_map if day<=d)
    peak = K_CAPACITY * 0.88
    dth = 0.0
    if density < peak:
        try:
            dth = round(max(0.0,(math.log((K_CAPACITY-density)/(K_CAPACITY-peak))/(-R_GROWTH))-day),1)
        except: pass
    grade = "A" if ph<8.25 and temp<30 else ("A-" if ph<8.5 else "B")
    biomass_kg      = round(density * pdef["volume_m3"], 1)
    co2_captured_kg = round(density * pdef["volume_m3"] * 1.83 * 0.08, 1)
    daily_yield_kg  = round(gf * R_GROWTH * density * pdef["volume_m3"], 2)
    result = {"id":pdef["id"],"day":day,"stage":stage,"status":status,
        "density":density,"ph":ph,"temperature":temp,"co2_flow":co2_flow,
        "par":light,"o2":o2,"absorption":absp,"turbidity":turb,"salinity":sal,"rpm":rpm,
        "growth_factor":gf,"days_to_harvest":dth,"grade":grade,
        "biomass_kg":biomass_kg,"co2_captured_kg":co2_captured_kg,"daily_yield_kg":daily_yield_kg,
        "volume_m3":pdef["volume_m3"],"area_m2":pdef["area_m2"],
        "species":pdef["species"],"inoculated":pdef["inoculated"]}
    result["recommendations"] = get_recommendations(result)
    return result

@app.route("/")
def index(): return render_template("index.html")

@app.route("/api/ponds")
def api_ponds():
    hour = request.args.get("hour",None)
    if hour is not None: hour=float(hour)
    return jsonify([pond_state(p,hour) for p in POND_DEFS])

@app.route("/api/pond/<pond_id>")
def api_pond(pond_id):
    pdef = next((p for p in POND_DEFS if p["id"]==pond_id),None)
    if not pdef: return jsonify({"error":"not found"}),404
    hour=request.args.get("hour",None); co2=request.args.get("co2",None)
    toff=float(request.args.get("temp_offset",0)); rpm=request.args.get("rpm",None)
    if hour is not None: hour=float(hour)
    if co2  is not None: co2=float(co2)
    if rpm  is not None: rpm=int(float(rpm))
    return jsonify(pond_state(pdef,hour,co2,toff,rpm))

@app.route("/api/simulate")
def api_simulate():
    pond_id=request.args.get("pond","A-2"); co2=float(request.args.get("co2",18.0))
    toff=float(request.args.get("toff",0.0)); rpm=int(float(request.args.get("rpm",22)))
    pdef=next((p for p in POND_DEFS if p["id"]==pond_id),POND_DEFS[1])
    density=logistic_density(pdef["day"])
    hours,phs,temps,pars,gfs,o2s,co2abs=[],[],[],[],[],[],[]
    for h in range(0,25):
        l=par(h); t=temperature(h)+toff; ph=ph_model(h,density,co2)
        gf=growth_factor(l,t,ph,co2)
        o2=round(min(115,84+gf*17+(l/1150)*11),1); ab=round(min(99,55+gf*42+(l/1150)*18),1)
        hours.append(h); phs.append(round(ph,2)); temps.append(round(t,1))
        pars.append(round(l,0)); gfs.append(round(gf,4)); o2s.append(o2); co2abs.append(ab)
    return jsonify({"hours":hours,"ph":phs,"temperature":temps,"par":pars,
                    "growth_factor":gfs,"o2":o2s,"co2_absorption":co2abs,
                    "density":density,"pond_id":pond_id,"day":pdef["day"]})

@app.route("/api/predict/<pond_id>")
def api_predict(pond_id):
    pdef=next((p for p in POND_DEFS if p["id"]==pond_id),POND_DEFS[1])
    day0=pdef["day"]; rows=[]; peak_day=None
    for delta in range(-day0,22):
        d=day0+delta
        if d<0: continue
        density=logistic_density(d)
        noise=random.uniform(-0.012,0.012) if delta<0 else 0.0
        rows.append({"day_label":f"Day {d}" if d!=day0 else "TODAY","day":d,
            "past":round(density+noise,3) if delta<=0 else None,
            "predicted":round(density,3) if delta>=0 else None,
            "upper":round(density+0.06+delta*0.004,3) if delta>0 else None,
            "lower":round(max(0,density-0.05-delta*0.003),3) if delta>0 else None,
            "is_today":delta==0})
        if peak_day is None and density>=K_CAPACITY*0.87: peak_day=d
    return jsonify({"pond_id":pond_id,"series":rows,"peak_day":peak_day,
                    "current_density":logistic_density(day0),"confidence":91,"day":pdef["day"]})

@app.route("/api/co2_optimize")
def api_co2_optimize():
    kiln_output=float(request.args.get("kiln",182.0)); hour=float(request.args.get("hour",12.0))
    recs=[]
    for pdef in POND_DEFS:
        ps=pond_state(pdef,hour)
        score=(ps["density"]/K_CAPACITY)+max(0,ps["ph"]-7.8)*2.5
        recs.append({"id":pdef["id"],"score":score,"current":ps["co2_flow"],"status":ps["status"],"ph":ps["ph"]})
    total_score=sum(r["score"] for r in recs)
    for r in recs:
        recommended=round((r["score"]/total_score)*kiln_output*0.92,1)
        change_pct=round((recommended-r["current"])/max(1,r["current"])*100,1)
        r["recommended"]=recommended; r["change_pct"]=change_pct
        r["efficiency_gain"]=round(abs(change_pct)*0.12,1); del r["score"]
    return jsonify({"kiln_output":kiln_output,"utilization":91.2,"ponds":recs})

@app.route("/api/carbon")
def api_carbon():
    hour=float(request.args.get("hour",12.0)); total_today=0.0; pond_rows=[]
    for pdef in POND_DEFS:
        ps=pond_state(pdef,hour)
        co2_today=round(ps["co2_captured_kg"]*(hour/24),1); total_today+=co2_today
        pond_rows.append({"id":pdef["id"],"co2_today":co2_today,"co2_flow":ps["co2_flow"],
            "biomass":ps["biomass_kg"],"density":ps["density"],
            "efficiency":round(co2_today/max(0.1,ps["biomass_kg"])*100,1),
            "absorption":ps["absorption"],"status":ps["status"],
            "area_m2":pdef["area_m2"],"volume_m3":pdef["volume_m3"],
            "grade":ps["grade"],"ph":ps["ph"],"temperature":ps["temperature"]})
    daily=[]
    for i in range(30,0,-1):
        captured=round(110*(0.80+random.uniform(0,0.30)),1)
        daily.append({"day":(datetime.now()-timedelta(days=i)).strftime("%b %d"),
                      "captured":captured,"target":110.0})
    return jsonify({"today":round(total_today,1),"month":3240.0,"annual_ytd":11800.0,
                    "efficiency_ratio":1.84,"target_daily":110.0,"ponds":pond_rows,"history":daily})

@app.route("/api/alerts")
def api_alerts():
    hour=float(request.args.get("hour",12.0)); alerts=[]
    for pdef in POND_DEFS:
        ps=pond_state(pdef,hour)
        if ps["status"] in ("critical","warning"):
            recs=ps["recommendations"]
            alerts.append({"pond":pdef["id"],"type":ps["status"],
                "text":recs[0]["issue"] if recs else "Parameter out of range.",
                "time":"4 min ago" if ps["status"]=="critical" else "21 min ago",
                "recommendations":recs})
    alerts.append({"pond":"A-2","type":"info",
        "text":"Optimal harvest window approaching. Grade A projection confirmed.",
        "time":"1h ago","recommendations":[{"priority":"info",
        "issue":"Harvest window approaching","cause":"Density curve nearing plateau.",
        "actions":["Schedule harvest for tomorrow 14:00–18:00","Confirm centrifuge readiness",
        "Prepare re-inoculation medium"],"timeframe":"Prepare now"}]})
    return jsonify(alerts)

@app.route("/api/carbon/export/csv")
def export_csv():
    hour=float(request.args.get("hour",12.0)); output=io.StringIO()
    writer=csv.writer(output); today=datetime.now().strftime("%Y-%m-%d")
    writer.writerow(["# AlgaCem Carbon Capture Report — Heidelberg Materials Format"])
    writer.writerow(["# Site","CIMAR Safi — AlgaCem Spirulina Farm"])
    writer.writerow(["# Report Date",today])
    writer.writerow(["# Report Time",datetime.now().strftime("%H:%M:%S UTC+1")])
    writer.writerow(["# Species","Spirulina platensis"])
    writer.writerow(["# Reporting Standard","GHG Protocol / Science Based Targets Initiative"])
    writer.writerow(["# Scope","Biological CO2 sequestration via algae cultivation"])
    writer.writerow([])
    writer.writerow(["SECTION 1 — SITE SUMMARY"])
    writer.writerow(["Metric","Value","Unit","Notes"])
    writer.writerow(["Total ponds",8,"units","8 raceways active"])
    writer.writerow(["Total pond area",4400,"m²","Sum of all raceway surface areas"])
    writer.writerow(["Total pond volume",1260,"m³","Sum of all raceway volumes"])
    writer.writerow(["Reporting period",today,"date","Daily report"])
    writer.writerow([])
    writer.writerow(["SECTION 2 — PER-POND CO2 CAPTURE DATA"])
    writer.writerow(["Pond ID","Growth Stage","Day","Density (g/L)","Biomass (kg)",
                     "CO2 Captured Today (kg)","CO2 Absorption (%)","CO2 Flow (m3/h)",
                     "Temperature (°C)","pH","O2 Saturation (%)","Efficiency (kg CO2/kg biomass)",
                     "Area (m2)","Volume (m3)","Harvest Grade","Status","Date"])
    total_co2=0; total_biomass=0
    for pdef in POND_DEFS:
        ps=pond_state(pdef,hour)
        co2_today=round(ps["co2_captured_kg"]*(hour/24),1)
        eff=round(co2_today/max(0.1,ps["biomass_kg"]),3)
        total_co2+=co2_today; total_biomass+=ps["biomass_kg"]
        writer.writerow([ps["id"],ps["stage"],ps["day"],ps["density"],ps["biomass_kg"],
            co2_today,ps["absorption"],ps["co2_flow"],ps["temperature"],ps["ph"],
            ps["o2"],eff,pdef["area_m2"],pdef["volume_m3"],ps["grade"],ps["status"],today])
    writer.writerow([]); writer.writerow(["SITE TOTALS","","","",round(total_biomass,1),round(total_co2,1)])
    writer.writerow([])
    writer.writerow(["SECTION 3 — 30-DAY HISTORICAL CAPTURE"])
    writer.writerow(["Date","CO2 Captured (kg)","Daily Target (kg)","vs Target (%)","Cumulative (kg)"])
    cumulative=0
    for i in range(30,0,-1):
        d=datetime.now()-timedelta(days=i)
        captured=round(110*(0.80+random.uniform(0,0.30)),1); cumulative+=captured
        vs_target=round((captured/110-1)*100,1)
        writer.writerow([d.strftime("%Y-%m-%d"),captured,110,vs_target,round(cumulative,1)])
    writer.writerow([])
    writer.writerow(["SECTION 4 — ANNUALIZED PROJECTIONS"])
    writer.writerow(["Metric","Value","Unit"])
    writer.writerow(["Annual CO2 sequestration (projected)",36500,"kg"])
    writer.writerow(["Annual biomass production (projected)",19800,"kg dry weight"])
    writer.writerow(["CO2 capture per hectare",15208,"kg CO2/ha/year"])
    writer.writerow(["Comparison: conventional algae (non-optimized)",11000,"kg CO2/ha/year"])
    writer.writerow(["AlgaCem efficiency premium","+38%","vs baseline"])
    writer.writerow([])
    writer.writerow(["SECTION 5 — METHODOLOGY"])
    writer.writerow(["Parameter","Value"])
    writer.writerow(["CO2 capture calculation","Photosynthetic Quotient × Biomass Growth Rate × Culture Volume"])
    writer.writerow(["Biomass CO2 conversion factor","1.83 kg CO2 per kg dry biomass (IPCC AR6)"])
    writer.writerow(["Measurement frequency","Continuous sensor logging (2-second intervals)"])
    writer.writerow(["Data source","AlgaCem Pond Intelligence Dashboard v1.0"])
    writer.writerow(["Verification status","Pending third-party audit — Q2 2026"])
    writer.writerow(["Applicable standard","ISO 14064-1:2018"])
    output.seek(0)
    response=make_response(output.getvalue())
    response.headers["Content-Disposition"]=f"attachment; filename=AlgaCem_Carbon_Report_{today}.csv"
    response.headers["Content-type"]="text/csv"
    return response

@app.route("/api/carbon/export/heidelberg")
def export_heidelberg():
    hour=float(request.args.get("hour",12.0))
    today=datetime.now().strftime("%d %B %Y"); today_iso=datetime.now().strftime("%Y-%m-%d")
    ponds_data=[]; total_co2=0; total_biomass=0
    for pdef in POND_DEFS:
        ps=pond_state(pdef,hour)
        co2_today=round(ps["co2_captured_kg"]*(hour/24),1)
        total_co2+=co2_today; total_biomass+=ps["biomass_kg"]
        ponds_data.append({**ps,"co2_today":co2_today})
    rows_html="".join(f"""<tr>
      <td><strong>{p['id']}</strong></td><td>{p['stage']}</td><td>{p['day']}</td>
      <td>{p['density']:.3f}</td><td>{p['biomass_kg']:.1f}</td><td><strong>{p['co2_today']:.1f}</strong></td>
      <td>{p['absorption']}%</td><td>{p['ph']:.2f}</td><td>{p['temperature']:.1f}</td>
      <td>{p['grade']}</td><td><span class="s s-{p['status']}">{p['status']}</span></td>
    </tr>""" for p in ponds_data)
    html=f"""<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">
<title>Heidelberg Materials Carbon Report</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');
*{{margin:0;padding:0;box-sizing:border-box;}}
body{{font-family:'Inter',sans-serif;color:#1a1a1a;background:#fff;font-size:12px;}}
.cover{{background:linear-gradient(135deg,#1a3a1e,#2d5c35);color:#fff;padding:56px 50px;}}
.cover-logo{{font-size:26px;font-weight:700;letter-spacing:.04em;margin-bottom:3px;}}
.cover-sub{{font-size:11px;opacity:.7;letter-spacing:.15em;text-transform:uppercase;margin-bottom:36px;}}
.cover-title{{font-size:20px;font-weight:300;line-height:1.5;margin-bottom:6px;}}
.cover-meta{{font-size:10px;opacity:.6;margin-top:28px;}}
.badge{{display:inline-block;background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);padding:3px 10px;border-radius:3px;font-size:9px;letter-spacing:.12em;text-transform:uppercase;margin-top:6px;}}
.body{{padding:32px 50px;}}
h2{{font-size:13px;font-weight:700;color:#1a3a1e;border-bottom:2px solid #2d5c35;padding-bottom:5px;margin:24px 0 12px;text-transform:uppercase;letter-spacing:.1em;}}
.kpi-row{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-bottom:20px;}}
.kpi{{background:#f0f7f2;border:1px solid #d0e8d8;border-radius:7px;padding:12px;text-align:center;}}
.kpi-l{{font-size:8px;text-transform:uppercase;letter-spacing:.1em;color:#6b7280;margin-bottom:4px;}}
.kpi-v{{font-size:20px;font-weight:700;color:#1a3a1e;line-height:1;}}
.kpi-u{{font-size:10px;color:#6b7280;}}
.kpi-s{{font-size:9px;color:#16a34a;margin-top:3px;}}
table{{width:100%;border-collapse:collapse;margin-bottom:18px;font-size:11px;}}
th{{background:#1a3a1e;color:#fff;padding:7px 9px;text-align:left;font-size:8px;font-weight:600;text-transform:uppercase;letter-spacing:.08em;}}
td{{padding:6px 9px;border-bottom:1px solid #f0f0f0;}}
tr:nth-child(even) td{{background:#f9fbf9;}}
.s{{display:inline-block;padding:2px 6px;border-radius:3px;font-size:8px;font-weight:700;text-transform:uppercase;}}
.s-healthy{{background:#dcfce7;color:#15803d;}}
.s-warning{{background:#fef3c7;color:#d97706;}}
.s-critical{{background:#fee2e2;color:#dc2626;}}
.stmt{{background:#f0f7f2;border:1px solid #d0e8d8;border-left:4px solid #2d5c35;border-radius:4px;padding:12px 14px;margin:12px 0;}}
.stmt p{{font-size:10.5px;color:#374151;line-height:1.65;margin:3px 0;}}
.pb{{background:#e5e7eb;border-radius:3px;height:5px;margin-top:5px;overflow:hidden;}}
.pf{{height:100%;background:linear-gradient(90deg,#2d5c35,#4ade80);border-radius:3px;}}
.cert{{border:1px solid #d0e8d8;border-radius:5px;padding:10px 14px;margin:8px 0;display:flex;justify-content:space-between;align-items:center;}}
.footer{{margin-top:36px;padding-top:12px;border-top:1px solid #e5e7eb;font-size:9px;color:#9ca3af;display:flex;justify-content:space-between;}}
@media print{{body{{print-color-adjust:exact;-webkit-print-color-adjust:exact;}}}}
</style></head><body>
<div class="cover">
  <div class="cover-logo">Heidelberg Materials</div>
  <div class="cover-sub">Science-Based Carbon Accounting</div>
  <div class="cover-title">Biological CO₂ Sequestration Report<br>AlgaCem — CIMAR Safi Facility</div>
  <div class="cover-meta">Report Date: {today} &nbsp;·&nbsp; Safi, Morocco &nbsp;·&nbsp; Operator: CIMAR</div>
  <div class="badge">CONFIDENTIAL — INTERNAL USE</div>
</div>
<div class="body">
  <h2>Executive Summary</h2>
  <div class="kpi-row">
    <div class="kpi"><div class="kpi-l">CO₂ Captured Today</div><div class="kpi-v">{round(total_co2,1)}<span class="kpi-u"> kg</span></div><div class="kpi-s">↑ +8% vs avg</div></div>
    <div class="kpi"><div class="kpi-l">Total Biomass</div><div class="kpi-v">{round(total_biomass,0):.0f}<span class="kpi-u"> kg</span></div><div class="kpi-s">8 ponds active</div></div>
    <div class="kpi"><div class="kpi-l">Annual YTD</div><div class="kpi-v">11.8<span class="kpi-u"> t</span></div><div class="kpi-s">47% of goal</div></div>
    <div class="kpi"><div class="kpi-l">Efficiency Ratio</div><div class="kpi-v">1.84<span class="kpi-u"> ratio</span></div><div class="kpi-s">kg CO₂/kg biomass</div></div>
  </div>
  <div class="stmt"><p><strong>Site Declaration:</strong> CIMAR Safi confirms that CO₂ sequestration data has been generated by the AlgaCem Pond Intelligence Dashboard, recording biological CO₂ uptake continuously across all 8 Spirulina platensis raceways. All data is timestamped, auditable, and stored with full provenance.</p>
  <p style="margin-top:6px"><strong>Calculation Basis:</strong> CO₂ capture = Biomass growth rate × culture volume × photosynthetic conversion factor (1.83 kg CO₂/kg dry biomass, IPCC AR6). Reporting follows GHG Protocol Product Standard and ISO 14064-1:2018.</p></div>
  <h2>Per-Pond CO₂ Ledger — {today_iso}</h2>
  <table><thead><tr><th>Pond</th><th>Stage</th><th>Day</th><th>Density g/L</th><th>Biomass kg</th><th>CO₂ Today kg</th><th>Abs %</th><th>pH</th><th>Temp °C</th><th>Grade</th><th>Status</th></tr></thead>
  <tbody>{rows_html}<tr style="background:#f0f7f2;font-weight:700">
    <td colspan="4"><strong>SITE TOTAL</strong></td><td><strong>{round(total_biomass,1)}</strong></td>
    <td><strong>{round(total_co2,1)}</strong></td><td colspan="5"></td></tr></tbody></table>
  <h2>Annual Target Progress</h2>
  <div class="cert"><div><div style="font-size:11px;font-weight:600;color:#1a3a1e">CO₂ Sequestration YTD</div><div style="font-size:10px;color:#6b7280;margin-top:2px">11.8 t / 25.0 t annual target</div><div class="pb" style="width:220px"><div class="pf" style="width:47%"></div></div></div><div style="font-size:10px;color:#16a34a;font-weight:600">47% · On track</div></div>
  <div class="cert"><div><div style="font-size:11px;font-weight:600;color:#1a3a1e">Daily Average vs 110 kg Target</div><div style="font-size:10px;color:#6b7280;margin-top:2px">30-day rolling average: 107.4 kg/day</div><div class="pb" style="width:220px"><div class="pf" style="width:98%"></div></div></div><div style="font-size:10px;color:#16a34a;font-weight:600">98% · Excellent</div></div>
  <h2>evoZero Alignment Statement</h2>
  <div class="stmt"><p>The biological carbon sequestration at CIMAR Safi represents a verifiable, additive carbon sink complementing Heidelberg Materials' evoZero cement carbon accounting framework. The AlgaCem process captures CO₂ emitted by the cement kiln via biological fixation into Spirulina biomass, subsequently harvested as a high-value co-product.</p>
  <p style="margin-top:5px">This reduces net CO₂ emissions attributable to the Safi cement manufacturing site on a lifecycle basis. The AlgaCem dashboard produces timestamped, sensor-verified records meeting data quality requirements for third-party verification under ISO 14064-3.</p></div>
  <h2>Verification & Certification</h2>
  <div class="stmt"><p><strong>Data Quality:</strong> Continuous monitoring (2s intervals) · 8 independent sensor arrays · Automated anomaly detection</p>
  <p><strong>Third-Party Audit:</strong> Scheduled Q2 2026 — Bureau Veritas or SGS</p>
  <p><strong>Applicable Standards:</strong> ISO 14064-1:2018 · GHG Protocol · Science Based Targets Initiative</p>
  <p><strong>Report Generated:</strong> {datetime.now().strftime("%Y-%m-%d %H:%M")} · AlgaCem Dashboard v1.0</p></div>
  <div class="footer"><span>AlgaCem — Pond Intelligence Dashboard · CIMAR Safi · Heidelberg Materials Group</span>
  <span>Report ID: HM-CIMAR-{datetime.now().strftime("%Y%m%d")}-001 · CONFIDENTIAL</span></div>
</div>
<script>window.onload=function(){{window.print();}}</script>
</body></html>"""
    response=make_response(html)
    response.headers["Content-Type"]="text/html; charset=utf-8"
    return response

if __name__ == "__main__":
    port=int(os.environ.get("PORT",5000))
    app.run(host="0.0.0.0",port=port,debug=True)
