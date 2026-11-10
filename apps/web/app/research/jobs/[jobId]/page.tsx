import { ResearchJobLivePage } from "../../../../features/research/components/research-job-live-page";

export default async function ResearchJobPage({ params }: { params: Promise<{ jobId: string }> }) {
  return <ResearchJobLivePage jobId={(await params).jobId} />;
}
