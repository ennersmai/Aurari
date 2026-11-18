import { useEffect } from 'react';
import { useRouter } from 'next/router';

export default function ChatNewRedirect() {
  const router = useRouter();

  useEffect(() => {
    // Redirect to the main chat page
    // We use replace to avoid keeping /chat/new in the history
    router.replace('/chat');
  }, [router]);

  return null; // Render nothing while redirecting
}
