import { Link } from "react-router-dom";
import { Logo, CmapBar, Footer } from "../components/Layout.jsx";

export default function NotFound() {
  return (
    <>
      <Logo />
      <CmapBar />
      <div className="card center" style={{ maxWidth: 480, margin: "48px auto 0" }}>
        <h1 style={{ fontSize: 28, marginBottom: 12 }}>Page not found</h1>
        <Link className="btn" to="/">Go to the home page</Link>
      </div>
      <Footer />
    </>
  );
}
