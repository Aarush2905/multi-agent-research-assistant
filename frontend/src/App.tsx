import { Route, Routes } from "react-router-dom";
import { NewResearchPage } from "./pages/NewResearchPage";
import { RunPage } from "./pages/RunPage";

function App() {
  return (
    <Routes>
      <Route path="/" element={<NewResearchPage />} />
      <Route path="/runs/:runId" element={<RunPage />} />
    </Routes>
  );
}

export default App;
