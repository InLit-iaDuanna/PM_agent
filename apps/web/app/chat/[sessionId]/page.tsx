import { ChatSessionLivePage } from "../../../features/research/components/chat-session-live-page";

export default async function ChatSessionPage({ params }: { params: { sessionId: string } }) {
  return <ChatSessionLivePage sessionId={params.sessionId} />;
}
