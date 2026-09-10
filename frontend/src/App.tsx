import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider, RequireAuth } from "./Auth";
import Calculator from "./Calculator";
import { FxRateProvider } from "./FxRateContext";
import Layout from "./Layout";
import Login from "./Login";
import Lots from "./Lots";
import RestorationCalc from "./RestorationCalc";
import Team from "./Team";

function ProtectedLayout() {
  return (
    <FxRateProvider>
      <Layout />
    </FxRateProvider>
  );
}

export default function App() {
  return (
    <AuthProvider>
      <Routes>
        <Route path="/login" element={<Login />} />
        <Route element={<RequireAuth />}>
          <Route element={<ProtectedLayout />}>
            <Route path="/" element={<Lots key="copart" platform="copart" />} />
            <Route path="/bidcars" element={<Lots key="bidcars" platform="bidcars" />} />
            <Route path="/restoration" element={<RestorationCalc />} />
            <Route path="/calc" element={<main className="page-main"><Calculator /></main>} />
            <Route path="/team" element={<Team />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Route>
      </Routes>
    </AuthProvider>
  );
}
