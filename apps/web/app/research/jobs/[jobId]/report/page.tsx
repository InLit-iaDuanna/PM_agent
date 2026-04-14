import { ResearchReportPageRefactored } from "../../../../../features/research/components/research-report-page-refactored";

export default async function ResearchReportRoute({ params }: { params: { jobId: string } }) {
  return <ResearchReportPageRefactored jobId={params.jobId} />;
}
