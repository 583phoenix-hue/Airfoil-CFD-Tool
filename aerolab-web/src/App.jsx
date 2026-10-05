import { lazy, Suspense } from "react";
import { Routes, Route } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import Home from "./pages/Home.jsx";
import About from "./pages/About.jsx";
import ChooseMode from "./pages/ChooseMode.jsx";
import NotFound from "./pages/NotFound.jsx";

// Tool pages (and Plotly with them) are split out so the home page stays small.
const Analysis = lazy(() => import("./pages/Analysis.jsx"));
const InverseDesign = lazy(() => import("./pages/InverseDesign.jsx"));
const Aeroelasticity = lazy(() => import("./pages/Aeroelasticity.jsx"));
const AeroRun = lazy(() => import("./pages/AeroRun.jsx"));

const Loading = () => <div className="caption" style={{ padding: "3rem 0", textAlign: "center" }}>Loading…</div>;

export default function App() {
  return (
    <Suspense fallback={<Loading />}>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Home />} />
          <Route path="/about" element={<About />} />
          <Route path="/choose" element={<ChooseMode />} />
          <Route path="/analysis" element={<Analysis />} />
          <Route path="/inverse-design" element={<InverseDesign />} />
          <Route path="/aeroelasticity" element={<Aeroelasticity />} />
          <Route path="/aeroelasticity/:module" element={<AeroRun />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </Suspense>
  );
}
