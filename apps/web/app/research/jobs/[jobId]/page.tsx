import { ResearchJobLivePage } from "../../../../features/research/components/research-job-live-page";

export default async function ResearchJobPage({ params }: { params: { jobId: string } }) {
  return <ResearchJobLivePage jobId={params.jobId} />;
}
