import { ResearchReportPageRefactored } from "../../../../../features/research/components/research-report-page-refactored";

export default async function ResearchReportRoute({ params }: { params: Promise<{ jobId: string }> }) {
  return <ResearchReportPageRefactored jobId={(await params).jobId} />;
}
