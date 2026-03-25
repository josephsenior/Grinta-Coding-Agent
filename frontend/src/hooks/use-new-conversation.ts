import { useNavigate } from "react-router-dom";

/** Opens a fresh chat UI; the server conversation is created on first send (see Chat page). */
export function useNewConversation() {
  const navigate = useNavigate();

  const create = () => {
    navigate("/chat/new");
  };

  return {
    create,
    isPending: false,
  };
}
