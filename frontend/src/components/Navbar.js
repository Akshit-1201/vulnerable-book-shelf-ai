// frontend/src/components/Navbar.js
import { Link } from "react-router-dom";

export default function Navbar({ isLoggedIn, handleLogout, role }) {
  return (
    <nav className="bg-gray-900 fixed top-0 left-0 w-full z-50 shadow-lg">
      <div className="max-w-7xl mx-auto px-6 py-3 flex justify-between items-center">
        <Link to="/" className="text-white font-bold text-xl">
          📚 BookShelf-AI
        </Link>
        <div className="space-x-6">
          {isLoggedIn ? (
            <>
              <Link to="/search" className="text-gray-300 hover:text-white">
                Search
              </Link>
              {role === "admin" && (
                <Link to="/admin" className="text-gray-300 hover:text-white">
                  Admin
                </Link>
              )}
              <button
                onClick={handleLogout}
                className="bg-red-500 hover:bg-red-600 text-white px-4 py-1 rounded-lg"
              >
                Logout
              </button>
            </>
          ) : (
            <>
              <Link to="/login" className="text-gray-300 hover:text-white">
                Login
              </Link>
              <Link to="/signup" className="text-gray-300 hover:text-white">
                Signup
              </Link>
            </>
          )}
        </div>
      </div>
    </nav>
  );
}
