import researchSteps from "../data/research-steps.json";
import industryTemplates from "../data/industry-templates.json";
import orchestrationPresets from "../data/orchestration-presets.json";
import goldenResearchBenchmarks from "../data/golden_research_benchmarks.json";
import researchDefaults from "@pm-agent/config/defaults/research-defaults.json";

export const stageWeights = researchDefaults.stageWeights;
export const depthPresets = researchDefaults.depthPresets;
export const researchStepsCatalog = researchSteps;
export const industryTemplateCatalog = industryTemplates;
export const orchestrationPresetCatalog = orchestrationPresets;
export const goldenResearchBenchmarkCatalog = goldenResearchBenchmarks;
