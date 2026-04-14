import { ResearchReportPage } from "../../../../../features/research/components/research-report-page";

export default async function ResearchReportRoute({ params }: { params: { jobId: string } }) {
  return <ResearchReportPage jobId={params.jobId} />;
}
