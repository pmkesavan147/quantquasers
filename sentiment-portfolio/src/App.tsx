import { Navigate, Route, Routes } from "react-router-dom";
import Shell from "@/components/Shell";
import Onboarding from "@/pages/Onboarding";
import PersonaReveal from "@/pages/PersonaReveal";
import Dashboard from "@/pages/Dashboard";
import SentimentInsights from "@/pages/SentimentInsights";
import Journal from "@/pages/Journal";
import { StoreProvider } from "@/lib/store";
import { ThemeProvider } from "@/lib/theme";

export default function App() {
  return (
    <ThemeProvider>
      <StoreProvider>
        <Routes>
          <Route
            path="/"
            element={
              <div className="mx-auto min-h-screen max-w-6xl px-6 py-12">
                <Onboarding />
              </div>
            }
          />
          <Route
            path="/persona"
            element={
              <div className="mx-auto flex min-h-screen max-w-6xl items-start px-6 py-12">
                <PersonaReveal />
              </div>
            }
          />
          {/* The Shell owns the status badges, so every post-onboarding screen
              shows mode, gate and model without asking for them. */}
          <Route element={<Shell />}>
            <Route path="/dashboard" element={<Dashboard />} />
            <Route path="/insights" element={<SentimentInsights />} />
            <Route path="/journal" element={<Journal />} />
          </Route>
          {/* /history was the old mock rebalance screen. */}
          <Route path="/history" element={<Navigate to="/journal" replace />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </StoreProvider>
    </ThemeProvider>
  );
}
