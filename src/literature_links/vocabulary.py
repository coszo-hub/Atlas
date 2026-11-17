#!/usr/bin/env python3
"""The method and concept vocabularies the literature links use, drafted from the corpus for review.

A method is what a paper does (ambient noise interferometry, template matching, eddy covariance); a concept is what
it studies (shallow slow slip, methane seepage, hypoxia). Each entry has a name, a group, a one-line definition and
the words papers use for it (a regular expression; case-sensitive where an acronym would otherwise match words).
Run with --counts to count, in the literature corpus, the papers whose abstract or full text uses each entry, and to
write the review table (vocabulary_review.md) and the vocabulary (vocabulary.json).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
I = re.I

# (id, name, group, definition, pattern, flags[, parent]): a child (stacked sills) is also its parent (magma reservoirs).
METHODS = [
    # Seismology
    ("ambient-noise-interferometry", "Ambient noise interferometry", "seismology",
     "Cross-correlating ambient seismic or acoustic noise between sensors (or components) to measure Green's functions and their changes (dv/v).",
     r"ambient (?:seismic )?noise (?:cross[- ]?)?correlation|noise (?:cross[- ]?)?correlation functions?|(?:ambient |seismic |passive |coda[- ]wave )?noise interferometry|seismic interferometry|coda[- ]wave interferometry|\bNCCFs?\b|\bdv/v\b|relative (?:seismic )?velocity (?:changes?|variations?)|seismic velocity (?:changes?|variations?)", I),
    ("earthquake-location", "Earthquake location and relocation", "seismology",
     "Locating and relocating earthquake hypocenters (double-difference, NonLinLoc, HYPO71) from arrival times.",
     r"earthquake (?:locations?|relocations?)|hypocent(?:er|re)s? (?:location|relocation)|double[- ]difference|\bhypoDD\b|NonLinLoc|HYPO71|relocated (?:earthquakes|events|hypocent)", I),
    ("earthquake-detection", "Earthquake detection and cataloging", "seismology",
     "Detecting and picking events to build catalogs (STA/LTA, phase pickers, automated catalogs).",
     r"earthquake (?:detection|catalog(?:ue)?s?)|\bSTA/LTA\b|phase pick(?:ing|er)|PhaseNet|EQTransformer|automat(?:ed|ic) (?:detection|catalog)", I),
    ("template-matching", "Template matching (matched filter)", "seismology",
     "Scanning continuous data with waveform templates of known events to detect repeats.",
     r"template[- ]matching|matched[- ]filter", I),
    ("seismic-tomography", "Seismic tomography and waveform inversion", "seismology",
     "Imaging seismic velocity structure from travel times or full waveforms.",
     r"tomograph\w*|full[- ]waveform inversion|\bFWI\b|travel[- ]?time inversion", I),
    ("seismic-reflection", "Seismic reflection imaging", "seismology",
     "Imaging subsurface structure with active-source multichannel or 3-D reflection surveys.",
     r"seismic reflection|multichannel seismic|\bMCS\b|3-?D seismic|reflection (?:profil|imag|data)", I),
    ("focal-mechanisms", "Focal mechanisms and moment tensors", "seismology",
     "Determining earthquake faulting geometry from polarities or moment tensor inversion.",
     r"focal mechanisms?|moment tensors?", I),
    ("source-parameters", "Earthquake source parameters", "seismology",
     "Stress drop, corner frequency and seismic moment from source spectra.",
     r"stress drops?|corner frequenc|source spectr", I),
    ("b-value", "b-value / frequency-magnitude analysis", "seismology",
     "The Gutenberg-Richter b value as a measure of the earthquake size distribution and stress.",
     r"\bb[- ]values?\b|Gutenberg[- ]Richter|frequency[- ]magnitude", I),
    ("tidal-triggering", "Tidal triggering and modulation analysis", "seismology",
     "Testing how tidal stresses modulate earthquake (or seep, tremor) rates.",
     r"tidal (?:triggering|modulation|stress(?:es)?|loading)|tidally (?:triggered|modulated)", I),
    ("seafloor-compliance", "Seafloor compliance", "seismology",
     "The seafloor's deformation under infragravity-wave pressure, inverted for shear velocity.",
     r"seafloor compliance|compliance (?:function|measurement|method)", I),
    ("surface-waves", "Surface-wave dispersion", "seismology",
     "Rayleigh/Love wave dispersion and phase velocity for crustal and lithospheric structure.",
     r"surface[- ]wave|Rayleigh[- ]wave|dispersion curves?|phase[- ]velocit", I),
    ("tremor-detection", "Tremor detection and location", "seismology",
     "Detecting and locating tectonic or volcanic tremor (envelope cross-correlation, beamforming).",
     r"tremor (?:detection|location|catalog)|envelope cross[- ]correlation|detect\w* (?:tectonic )?tremor", I),
    ("noise-removal", "Seismic noise characterization and removal", "seismology",
     "Characterizing and removing tilt, compliance and current noise from ocean-bottom seismic records.",
     r"tilt noise|compliance noise|noise removal|noise reduction|transfer function|current[- ](?:induced|generated) noise|noise sources?", I),
    # Geodesy and deformation
    ("seafloor-pressure-geodesy", "Seafloor pressure geodesy", "geodesy",
     "Measuring vertical seafloor deformation from bottom pressure records.",
     r"seafloor geodesy|(?:bottom|seafloor) pressure (?:record|measurement|data|time series|observation)s?|vertical (?:deformation|displacement)|pressure[- ]based geodesy", I),
    ("pressure-calibration", "Pressure-gauge self-calibration and drift correction", "geodesy",
     "In-situ calibration (deadweight piston gauge, A-0-A) to remove quartz gauge drift.",
     r"self[- ]calibrat\w*|drift[- ]correct\w*|\bA-0-A\b|deadweight|piston gauge|gauge drift", I),
    ("acoustic-ranging", "Acoustic ranging (horizontal geodesy)", "geodesy",
     "Direct-path acoustic ranging between transponders to measure horizontal extension.",
     r"acoustic (?:ranging|extensometer)s?|direct[- ]path (?:acoustic )?ranging|horizontal (?:geodesy|extension|deformation)|baseline (?:length|change)s?|GNSS-A", I),
    ("gnss-geodesy", "GNSS/GPS geodesy and leveling", "geodesy",
     "Onshore GPS/GNSS time series and leveling for strain, locking and slow slip.",
     r"\bGNSS\b|\bGPS\b|leveling|levelling", 0),
    ("deformation-modeling", "Deformation source modeling", "geodesy",
     "Modeling deformation with Mogi, sill, dike or finite-element sources.",
     r"\bMogi\b|deformation (?:source )?model\w*|point source|finite[- ]element|dike (?:intrusion )?model\w*|sill model\w*|analytical model\w*", I),
    ("eruption-forecasting", "Eruption forecasting", "geodesy",
     "Forecasting eruptions from inflation, seismicity or their patterns.",
     r"eruption forecast\w*|forecast\w* (?:the next |an |future )?eruption|inflation[- ]predictable", I),
    # Acoustics
    ("passive-acoustics", "Passive acoustic monitoring", "acoustics",
     "Listening with hydrophones to biological, geophysical and anthropogenic sound.",
     r"passive acoustic|hydrophone (?:data|recordings?|array)|acoustic monitoring", I),
    ("call-detection", "Animal call detection and classification", "acoustics",
     "Detecting, classifying and localizing marine mammal calls.",
     r"(?:whale|mammal|orca) (?:call|vocalization|detection|click)s?|call (?:detection|classification|localization)|vocalizations?", I),
    ("sound-levels", "Sound levels and soundscapes", "acoustics",
     "Measuring ambient sound levels, spectra and soundscape trends.",
     r"sound (?:pressure )?levels?|noise levels?|power spectral densit\w*|\bPSDs?\b|soundscapes?|ambient sound", I),
    ("hydroacoustic-tphases", "Hydroacoustic T-phase analysis", "acoustics",
     "Detecting earthquakes and eruptions from T-phases recorded by hydrophones (SOSUS).",
     r"T[- ]phases?|T[- ]waves?|hydroacoustic\w*|\bSOSUS\b", 0),
    ("sound-propagation", "Sound propagation and sound speed", "acoustics",
     "Acoustic propagation, sound speed structure, ducts and transmission loss.",
     r"sound[- ]speed|acoustic propagation|transmission loss|sound channel|acoustic duct|propagation loss", I),
    # Fiber sensing: the cable as the sensor.
    ("fiber-sensing", "Fiber-optic sensing", "fiber_sensing",
     "Using optical fiber itself as the sensor: distributed acoustic and temperature sensing, and optical fiber strain.",
     r"distributed acoustic sensing|\bDAS\b|distributed temperature sensing|\bDTS\b|fib(?:er|re)[- ]optic(?:al)? (?:sensing|strain\w*)|optical[- ]fib(?:er|re) (?:sensing|strain\w*)|\bSMART cables?\b", 0),
    ("das", "Distributed acoustic sensing (DAS)", "fiber_sensing",
     "Strain or strain rate along a fiber from Rayleigh backscatter, every few meters over tens of km.",
     r"distributed acoustic sensing|\bDAS\b", 0, "fiber-sensing"),
    ("dts", "Distributed temperature sensing (DTS)", "fiber_sensing",
     "Temperature along a fiber from Raman (or Brillouin) backscatter.",
     r"distributed temperature sensing|\bDTS\b", 0, "fiber-sensing"),
    ("fiber-strain", "Optical fiber strain (strainmeters)", "fiber_sensing",
     "Interferometric optical-fiber strainmeters measuring long-baseline strain on land or the seafloor.",
     r"optical[- ]fib(?:er|re) strain\w*|fib(?:er|re)[- ]optic(?:al)? strainmeters?|interferometric strainmeters?|laser strainmeters?|seafloor strainmeters?|strainmeters?", 0, "fiber-sensing"),
    ("sonar-imaging", "Sonar imaging of plumes and bubbles", "acoustics",
     "Imaging vent plumes and gas bubbles with multibeam or imaging sonar (COVIS, rotary sonar).",
     r"\bCOVIS\b|multibeam sonar|imaging sonar|rotary sonar|acoustic backscatter|water[- ]column (?:imaging|backscatter|acoustic)|acoustic flares?|bubble plume (?:imaging|detection)", 0),
    ("echosounder", "Echosounder bioacoustics", "acoustics",
     "Measuring zooplankton and fish with echosounders (EK60, ZPLSC).",
     r"echo ?sounders?|\bEK-?60\b|bio-?acoustic|acoustic scatter(?:ers|ing)|\bZPLSC\b", 0),
    # Oceanography
    ("profiling", "Water-column profiling (CTD, profilers, gliders)", "oceanography",
     "Measuring water-column properties with CTDs, profiling moorings and gliders.",
     r"\bCTDs?\b|shallow profiler|deep profiler|profiling (?:mooring|float|platform)|\bgliders?\b|vertical profiles?", 0),
    ("current-measurement", "Current measurement (ADCP, current meters)", "oceanography",
     "Measuring currents with ADCPs and point current meters.",
     r"\bADCPs?\b|acoustic Doppler|current meters?|velocimeters?", 0),
    ("eddy-covariance", "Eddy covariance (benthic flux)", "oceanography",
     "Measuring benthic oxygen flux by eddy correlation above the seafloor.",
     r"eddy (?:correlation|covariance)", I),
    ("ocean-modeling", "Numerical ocean modeling", "oceanography",
     "Regional ocean circulation models (ROMS) and particle tracking.",
     r"\bROMS\b|circulation model|ocean model\w*|regional model|particle tracking|Lagrangian", 0),
    ("data-assimilation", "Data assimilation", "oceanography",
     "Combining observations with models (Kalman filters, optimal interpolation).",
     r"data assimilation|Kalman|optimal interpolation", I),
    ("remote-sensing", "Satellite remote sensing", "oceanography",
     "Satellite observations of ocean color, temperature and sea level.",
     r"satellite|remote sensing|altimetr", I),
    ("time-series-analysis", "Time-series and spectral analysis", "oceanography",
     "Spectral, harmonic, wavelet and statistical analysis of long time series.",
     r"time[- ]series analys\w*|spectral analys\w*|wavelet|harmonic analys\w*|tidal analys\w*|cross[- ]spectr\w*", I),
    # Geochemistry and biology
    ("fluid-geochemistry", "Fluid and porewater geochemistry", "geochemistry_biology",
     "Sampling and analyzing vent fluids, porewaters and seawater chemistry.",
     r"vent fluids?|fluid sampl\w*|pore ?waters?|interstitial waters?|fluid chemistry|geochemi\w*", I),
    ("isotopes", "Stable and radiogenic isotopes", "geochemistry_biology",
     "Isotopic tracers (δ13C, δ18O, δD, helium, radiocarbon, U/Th) for sources and ages.",
     r"isotop\w*|δ13C|δ18O|δD\b|radiocarbon|\bU/Th\b|129I|3He", I),
    ("genomics", "Microbial genomics and sequencing", "geochemistry_biology",
     "16S rRNA, metagenomics, metatranscriptomics and genome sequencing of microbes.",
     r"metagenom\w*|metatranscriptom\w*|metaproteom\w*|16S rRNA|genome sequenc\w*|amplicon|sequencing", I),
    ("cultivation", "Microbial isolation and cultivation", "geochemistry_biology",
     "Isolating and growing strains to describe physiology and new taxa.",
     r"isolated (?:from|strain)|cultivat\w*|enrichment cultures?|pure cultures?|strain [A-Z]\w*\d|sp\. nov|gen\. nov", 0),
    ("incubation-experiments", "Incubation experiments and isotope probing", "geochemistry_biology",
     "In-situ or shipboard incubations, stable isotope probing (SIP) and rate measurements.",
     r"incubations?|stable isotope probing|\bSIP\b|rate measurements?", 0),
    ("imagery-analysis", "Seafloor imagery and video analysis", "geochemistry_biology",
     "Analyzing camera, video and photomosaic imagery of the seafloor and fauna.",
     r"\bvideo\b|imagery|image analys\w*|photo(?:graph\w*|mosaic\w*)|time[- ]lapse|still camera|HD camera|CamHD", I),
    ("machine-learning", "Machine learning", "geochemistry_biology",
     "Supervised and unsupervised learning, neural networks and deep learning.",
     r"machine learning|deep learning|neural networks?|random forest|convolutional|autoencoder|unsupervised|transformer model", I),
    # Geology and mapping
    ("seafloor-mapping", "Seafloor mapping and repeat bathymetry", "geology",
     "High-resolution and repeat bathymetry from AUVs, ships and ROVs.",
     r"bathymetr\w*|multibeam (?:bathymetry|survey|map\w*)|\bAUV\b|\bROV\b|repeat (?:survey|mapping)|high[- ]resolution (?:map|mapping)|side[- ]scan", 0),
    ("drilling-logging", "Scientific drilling, coring and logging", "geology",
     "Drilling and coring (ODP/IODP) and downhole logging.",
     r"\bODP\b|\bIODP\b|drilling|logging[- ]while[- ]drilling|\bLWD\b|piston core\w*|downhole|borehole", 0),
    ("em-surveys", "Electromagnetic and magnetotelluric surveys", "geology",
     "Controlled-source EM and magnetotelluric soundings of resistivity.",
     r"electromagnetic|\bCSEM\b|magnetotelluric", 0),
    ("potential-fields", "Gravity and magnetic surveys", "geology",
     "Gravity and magnetic anomaly measurements of crustal structure.",
     r"gravity (?:survey|measurement|anomal|data)\w*|magnetic (?:anomal|survey|structure|data)\w*|magnetization", I),
    ("petrology", "Petrology and lava geochemistry", "geology",
     "Petrology, glass and melt-inclusion chemistry of erupted lavas.",
     r"petrolog\w*|melt inclusions?|lava (?:geochemistry|composition|chemistry)|basalt (?:glass|geochemistry)|\bMORB\b", 0),
    ("paleoseismology", "Turbidite paleoseismology", "geology",
     "Dating turbidites and coastal records of past great earthquakes.",
     r"turbidite\w*|paleoseism\w*|paleo-?earthquake", I),
]

CONCEPTS = [
    # Subduction and the Cascadia margin
    ("megathrust-locking", "Megathrust locking and coupling", "subduction", "How strongly the plate interface is locked, accumulating strain.",
     r"locking|locked|coupling|strain accumulation|interseismic", I),
    ("slow-slip", "Slow slip events", "subduction", "Aseismic slip transients on the plate interface (including shallow SSEs).",
     r"slow[- ]slip|\bSSEs?\b|aseismic slip|slip transients?", 0),
    ("ets", "Episodic tremor and slip", "subduction", "Recurring tremor with slow slip downdip of the locked zone.",
     r"episodic tremor|\bETS\b", 0),
    ("tectonic-tremor", "Tectonic tremor and low-frequency earthquakes", "subduction", "Emergent tremor and LFE/VLFE slow earthquakes.",
     r"tectonic tremor|non-?volcanic tremor|low[- ]frequency earthquakes?|\bLFEs?\b|\bVLFEs?\b|very low[- ]frequency earthquakes?", 0),
    ("great-earthquakes", "Great megathrust earthquakes", "subduction", "M8-9 subduction earthquakes, their recurrence and rupture.",
     r"great (?:megathrust )?earthquakes?|megathrust (?:earthquakes?|ruptures?)|1700 (?:Cascadia )?earthquake|recurrence", I),
    ("tsunami", "Tsunamis", "subduction", "Tsunami generation, detection and warning.", r"tsunami\w*", I),
    ("early-warning", "Earthquake and tsunami early warning", "subduction", "Real-time warning systems and their offshore sensors.",
     r"early warning|\bEEW\b|ShakeAlert|G-FAST", 0),
    ("subduction-fluids", "Subduction zone fluids and overpressure", "subduction", "Fluid flow, pore pressure and overpressure in forearcs.",
     r"overpressur\w*|pore[- ]?(?:fluid )?pressure|fluid (?:migration|flow|expulsion|transport)|dewatering", I),
    ("accretionary-prism", "Accretionary prism, protothrusts and the deformation front", "subduction", "Structure of the accretionary wedge at the toe of the margin.",
     r"accretionary (?:prism|wedge|complex)|protothrust\w*|deformation front|d[ée]collement|frontal thrust", I),
    ("offshore-seismicity", "Offshore and plate-boundary seismicity", "subduction", "Earthquakes on and near the offshore plate boundary.",
     r"plate[- ]boundary (?:earthquakes|seismicity)|offshore (?:earthquakes|seismicity)|forearc seismicity|intraslab", I),
    ("subducted-seamounts", "Subducted seamounts", "subduction", "Seamounts on the downgoing plate and their effects.", r"subducted seamounts?|seamount subduction", I),
    ("shallow-slow-slip", "Shallow slow slip", "subduction", "Slow slip on the shallow megathrust or protothrusts, updip of the locked zone.",
     r"shallow (?:slow[- ]slip|SSEs?|aseismic slip)|(?:near[- ]trench|updip) slow[- ]slip|slow[- ]slip (?:near|at|on) (?:the trench|protothrusts?)|slow slip (?:event )?on protothrusts?", I, "slow-slip"),
    ("segmentation", "Subduction zone segmentation", "subduction", "Along-strike segments of the margin and their boundaries.",
     r"segmentation|segment boundar\w*|along[- ]strike (?:variation|segment)\w*|\bsegmented\b", I),
    ("faulting", "Faulting", "faults", "Faults and fault slip: normal, thrust and strike-slip.",
     r"\bfault(?:s|ing|ed)?\b|thrust faults?|normal faults?|strike[- ]slip", I),
    ("cascadia-strike-slip-faults", "Cascadia strike-slip faults", "faults", "The WNW-trending left-lateral strike-slip faults that cut the Oregon-Washington margin.",
     r"(?:strike[- ]slip|left[- ]lateral|wrench) faults?|\bWecoma\b|Daisy Bank|Alvin Canyon|Heceta|Coquille|Thompson Ridge|Nitinat|Kalaloch|Grays Canyon|Willapa", I, "faulting"),
    ("alvin-canyon-fault", "Alvin Canyon Fault", "faults", "A strike-slip fault near Hydrate Ridge that drains fluids from the margin (Pythia's Oasis).",
     r"Alvin Canyon", I, "cascadia-strike-slip-faults"),
    ("daisy-bank-fault", "Daisy Bank Fault", "faults", "A left-lateral strike-slip fault on the central Oregon shelf and slope.",
     r"Daisy Bank", I, "cascadia-strike-slip-faults"),
    # Volcanoes and ridges
    ("eruptions", "Submarine eruptions", "volcanic", "Eruptions at Axial and other ridges: timing, volume, dikes and lava.",
     r"eruptions?|erupted|eruptive", I),
    ("eruption-axial-1998", "Axial Seamount 1998 eruption", "volcanic", "The January 1998 eruption of Axial Seamount.",
     r"1998 (?:eruption|lava|event|swarm|episode)|(?:eruption|event|swarm) (?:of|in) (?:January |January-February )?1998|January\W+February 1998", I, "eruptions"),
    ("eruption-axial-2011", "Axial Seamount 2011 eruption", "volcanic", "The April 2011 eruption of Axial Seamount.",
     r"2011 (?:eruption|lava|event)|(?:eruption|event) (?:of|in) (?:April )?2011", I, "eruptions"),
    ("eruption-axial-2015", "Axial Seamount 2015 eruption", "volcanic", "The April 2015 eruption of Axial Seamount, recorded by the Cabled Array.",
     r"2015 (?:eruption|lava|event|diking)|(?:eruption|event) (?:of|in) (?:April )?2015", I, "eruptions"),
    ("eruption-coaxial-1993", "CoAxial segment 1993 dike intrusion", "volcanic", "The June-July 1993 dike intrusion and eruption on the CoAxial segment.",
     r"CoAxial|1993 (?:eruption|event|dike|diking|seismic)", I, "eruptions"),
    ("magma-reservoir", "Magma reservoirs and plumbing", "volcanic", "Melt storage, sills, the axial magma chamber and its supply.",
     r"magma (?:reservoir|chamber|plumbing|storage|supply|body|lens)|melt (?:lens|sill|reservoir|fraction)|\bAMC\b|magma supply", I),
    ("stacked-sills", "Stacked sills", "volcanic", "Several melt sills or lenses stacked beneath the summit.",
     r"stacked (?:melt )?(?:sills?|lenses)|multiple (?:melt )?(?:sills|lenses)|sill complex|melt lenses", I, "magma-reservoir"),
    ("inflation-cycle", "Inflation-deflation cycle", "volcanic", "Volcano uplift between eruptions and collapse during them.",
     r"inflation|deflation|re-?inflat\w*|uplift rate", I),
    ("dike-intrusion", "Dike intrusion and rifting", "volcanic", "Dike propagation along rift zones and seafloor spreading events.",
     r"dikes?|dykes?|diking|dyking|rifting|rift zones?|spreading event", I),
    ("ring-faults", "Caldera ring faults", "volcanic", "Faults around the caldera that accommodate inflation and deflation.",
     r"ring[- ]faults?|caldera faults?|caldera collapse|caldera formation", I, "faulting"),
    ("outward-dipping-faults", "Buried outward-dipping ring faults", "volcanic", "The buried, outward-dipping ring faults beneath Axial's caldera.",
     r"outward[- ]dipping|buried (?:ring )?faults?|ring[- ]fault system", I, "ring-faults"),
    ("lava-flows", "Lava flows and volcaniclastics", "volcanic", "Lava flow morphology, emplacement and pyroclastic deposits.",
     r"lava flows?|pillow|lobate|sheet flows?|pyroclastic|volcaniclastic|tephra|ash deposit", I),
    ("volcanic-seismicity", "Volcanic seismicity", "volcanic", "Earthquake swarms and microseismicity tied to volcanic activity.",
     r"microearthquakes?|earthquake swarms?|seismic swarms?|volcanic seismicity|volcano-tectonic", I),
    ("hotspot-volcanism", "Hotspot volcanism (Cobb hotspot)", "volcanic", "Hotspot volcanism and the Cobb hotspot's interaction with the ridge at Axial.",
     r"\bCobb\b|hot ?spot|plume[- ]ridge|intraplate volcan\w*", I),
    ("porosity", "Porosity and permeability", "volcanic", "Porosity and permeability of crust and sediments, controlling fluid flow.",
     r"porosit\w*|permeabilit\w*", I),
    ("crustal-structure", "Oceanic crustal structure and accretion", "volcanic", "Layering and formation of young oceanic crust.",
     r"crustal (?:structure|accretion|thickness)|oceanic crust|upper crust|sheeted dy?ke|layer 2A", I),
    ("tidal-forcing", "Tidal forcing of geological processes", "volcanic", "Tides modulating earthquakes, venting and seepage.",
     r"tidal (?:triggering|modulation|forcing|loading|stress)|\btides?\b", I),
    # Hydrothermal systems
    ("hydrothermal-venting", "Hydrothermal venting and plumes", "hydrothermal", "Vents, plumes and heat flux from hydrothermal systems.",
     r"hydrothermal (?:vent\w*|plumes?|discharge|activity|flux|circulation)|black smokers?|event plumes?|megaplumes?", I),
    ("diffuse-flow", "Diffuse flow", "hydrothermal", "Low-temperature diffuse venting from cracks and mats.", r"diffuse (?:flow|venting|vents?|fluids?)", I),
    ("vent-chemistry", "Vent fluid chemistry and phase separation", "hydrothermal", "Composition and evolution of vent fluids.",
     r"vent fluid (?:chemistry|composition)|phase separation|chlorinity|fluid composition", I),
    ("sulfide-chimneys", "Sulfide chimneys and mineral deposits", "hydrothermal", "Chimney growth and polymetallic sulfide deposits.",
     r"chimneys?|sulfide (?:deposits?|spire|minerals?)|anhydrite|massive sulfide", I),
    ("subseafloor-biosphere", "Subseafloor microbial biosphere", "hydrothermal", "Microbes living in and below young crust and vents.",
     r"subseafloor|sub-seafloor|deep biosphere|microbial communit\w*|thermophil\w*|hyperthermophil\w*|methanogen\w*", I),
    ("vent-ecology", "Vent ecosystems and fauna", "hydrothermal", "Animals and food webs at hydrothermal vents.",
     r"tubeworms?|vent (?:fauna|communit\w*|ecosystems?|animals?)|Ridgeia|polychaetes?|food webs?|chemosynthe\w*", I),
    # Methane and hydrates
    ("gas-hydrates", "Gas hydrates and free gas", "methane", "Methane hydrate stability, distribution and free gas beneath it.",
     r"gas hydrates?|methane hydrates?|hydrate stability|\bBSRs?\b|bottom[- ]simulating reflect\w*|free gas", 0),
    ("methane-seepage", "Methane seepage and bubble plumes", "methane", "Methane escaping from seeps as bubbles and dissolved gas.",
     r"methane (?:seep\w*|bubbles?|emissions?|release|venting|flux\w*)|cold seeps?|bubble plumes?|gas (?:seepage|venting|emissions?|flares?)|ebullition", I),
    ("aom", "Anaerobic oxidation of methane", "methane", "Methane consumed by archaeal-bacterial consortia in sediments.",
     r"anaerobic oxidation of methane|\bAOM\b|\bANME\w*|methanotroph\w*", 0),
    ("authigenic-carbonates", "Authigenic carbonates", "methane", "Carbonates precipitated from methane-derived carbon at seeps.",
     r"authigenic carbonates?|seep carbonates?|chemoherms?|clathrites?", I),
    ("seep-ecology", "Seep ecosystems", "methane", "Mats, clams and fauna at methane seeps.",
     r"Beggiatoa|Calyptogena|bacterial mats?|clam fields?|seep (?:fauna|communit\w*|ecosystems?|habitats?)", I),
    # Coastal and ocean processes
    ("upwelling", "Coastal upwelling and downwelling", "ocean", "Wind-driven upwelling and its seasonal cycle on the shelf.", r"upwelling|downwelling", I),
    ("hypoxia", "Hypoxia and deoxygenation", "ocean", "Low dissolved oxygen on the shelf and deoxygenation trends.",
     r"hypoxi\w*|deoxygenation|low[- ]oxygen|oxygen minimum|dissolved oxygen", I),
    ("acidification", "Ocean acidification and carbonate chemistry", "ocean", "pH, pCO2 and carbonate saturation changes.",
     r"acidification|\bpCO2\b|carbonate (?:chemistry|system|saturation)|aragonite", 0),
    ("marine-heatwaves", "Marine heatwaves and El Niño", "ocean", "The 2014-2016 warm Blob, El Niño and their effects.",
     r"marine heat ?waves?|\bBlob\b|El Ni[ñn]o|warm anomal\w*", 0),
    ("river-plumes", "River plumes and freshwater", "ocean", "Columbia River plume and freshwater influence on the shelf.",
     r"Columbia River|river plumes?|freshwater (?:input|discharge|plume)", I),
    ("internal-waves", "Internal waves and tides", "ocean", "Internal waves and internal tides on the shelf and slope.", r"internal (?:waves?|tides?|bores?)", I),
    ("ocean-circulation", "Ocean circulation and currents", "ocean", "Along-slope currents, undercurrents and circulation around seamounts.",
     r"undercurrent|along[- ]slope (?:flow|current)|circulation|boundary currents?|California Current", I),
    ("primary-production", "Phytoplankton and primary production", "ocean", "Chlorophyll, blooms and particulate organic carbon.",
     r"phytoplankton|chlorophyll|primary produc\w*|particulate organic|algal blooms?|harmful algal|domoic", I),
    ("zooplankton-fish", "Zooplankton, fish and diel migration", "ocean", "Pelagic animals and their vertical migration.",
     r"zooplankton|diel vertical migration|\bDVM\b|krill|fish(?:es)?\b|nekton", 0),
    ("benthic-processes", "Benthic boundary layer and seafloor fluxes", "ocean", "Sediment-water exchange and bottom boundary layer dynamics.",
     r"benthic (?:boundary layer|flux\w*|respiration|oxygen)|bottom boundary layer|sediment oxygen|seafloor flux", I),
    # Acoustics and biology
    ("marine-mammals", "Marine mammals", "acoustics_biology", "Whales and other marine mammals and their calls.",
     r"whales?|marine mammals?|orcas?|dolphins?|cetacean\w*", I),
    ("anthropogenic-noise", "Ship and anthropogenic noise", "acoustics_biology", "Shipping and other human-made underwater noise.",
     r"ship(?:ping)? noise|vessel noise|anthropogenic (?:noise|sound)|underwater radiated noise|container ship", I),
    ("weather-noise", "Wind, rain and wave noise", "acoustics_biology", "Ambient sound and seismic noise from wind, rain, waves and storms.",
     r"wind[- ](?:dependent|driven|generated) (?:noise|sound)|rain(?:fall)? noise|underwater rainfall|storms?|microseisms?|ocean waves|\bhum\b", I),
    ("ocean-thermometry", "Ocean thermometry", "acoustics_biology", "Measuring ocean temperature change from acoustic or seismic travel times.",
     r"ocean (?:acoustic )?thermometry|seismic ocean thermometry|travel[- ]time (?:changes|fluctuations)", I),
    # Observatories and instruments
    ("cabled-observatories", "Cabled seafloor observatories", "observatory", "Cabled observatory infrastructure, design and operations.",
     r"cabled (?:observator\w*|array|network)|seafloor observator\w*|\bNEPTUNE\b|Regional Cabled Array|\bOOI\b|Ocean Observatories Initiative", 0),
    ("pressure-drift", "Pressure gauge drift", "observatory", "Long-term drift of quartz pressure gauges, which mimics or hides deformation.",
     r"(?:gauge|sensor|pressure|quartz) drift|drift rates?|long[- ]term drift|exponential drift|drift (?:correction|removal)|drifts? (?:of|in) (?:the )?(?:pressure )?gauges?", I),
]


def corpus():
    """paper id -> (abstract-layer text, full text)."""
    abstract, full = defaultdict(str), defaultdict(list)
    for line in (ROOT / "data/Literature/chunks.jsonl").read_text().splitlines():
        c = json.loads(line)
        if c.get("document_type") == "literature_work":
            abstract[c["document_id"]] += " " + (c.get("text") or "")
    for line in (ROOT / "data/LiteratureFullText/chunks.jsonl").read_text().splitlines():
        c = json.loads(line)
        full[c["document_id"]].append(c.get("text") or "")
    return abstract, full


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--counts", action="store_true")
    args = parser.parse_args()
    def entry(kind, t):
        i, n, g, d, p, f, *parent = t
        return {"id": i, "name": n, "kind": kind, "group": g, "definition": d, "pattern": p, "ignore_case": bool(f),
                "parent": parent[0] if parent else None}
    entries = [entry("method", t) for t in METHODS] + [entry("concept", t) for t in CONCEPTS]
    ids = {e["id"] for e in entries}
    assert all(e["parent"] in ids for e in entries if e["parent"]), "a parent that is not an entry"
    if args.counts:
        abstract, full = corpus()
        for e in entries:
            rx = re.compile(e["pattern"], re.I if e["ignore_case"] else 0)
            e["papers_abstract"] = sum(1 for t in abstract.values() if rx.search(t))
            # In full text a word may be in the introduction or references: counted where two or more passages use it.
            e["papers_fulltext_2plus"] = sum(1 for ps in full.values() if sum(1 for p in ps if rx.search(p)) >= 2)
        (HERE / "vocabulary.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n")
        lines = ["# Method and concept vocabulary (draft for review)", "",
                 "Papers counted: the abstract layer (934 works) and, in full text (433 papers), papers with two or more passages using the entry.", ""]
        for kind in ("method", "concept"):
            lines += [f"## {kind.title()}s", "", "| Group | Entry | Under | Definition | Words papers use | Abstracts | Full text |", "|---|---|---|---|---|---|---|"]
            for e in sorted((x for x in entries if x["kind"] == kind), key=lambda x: (x["group"], -x["papers_abstract"])):
                words = e["pattern"].replace("|", " / ").replace("\\b", "")
                lines.append(f"| {e['group']} | **{e['name']}** | {e['parent'] or ''} | {e['definition']} | `{words[:140]}` | {e['papers_abstract']} | {e['papers_fulltext_2plus']} |")
            lines.append("")
        (HERE / "vocabulary_review.md").write_text("\n".join(lines) + "\n")
        for kind in ("method", "concept"):
            ks = [e for e in entries if e["kind"] == kind]
            print(kind, len(ks))
            for e in sorted(ks, key=lambda x: -x["papers_abstract"]):
                print(f"   {e['papers_abstract']:4} {e['papers_fulltext_2plus']:4}  {e['id']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
