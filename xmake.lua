-- lsp: xmake project -k compile_commands --lsp=clangd --outputdir=build
-- build: xmake build
--
-- Expected dependency layout (relative to <repo_root>)
--
-- <parent_dir>/
-- ├─ blender-hkx/                ← <repo_root>
-- │   └─ xmake.lua
-- │
-- └─ Havok SDK/
--     └─ 2010_2_0/
--         ├─ Source/
--         └─ Lib/
--             └─ win32_net_9-0/
--                 ├─ debug_multithreaded/
--                 │   └─ *.lib
--                 └─ release_multithreaded/
--                     └─ *.lib
add_rules("mode.debug", "mode.release")

-- Global settings (declared here to be inherited by niflib)
set_arch("x86") -- Because it depends on Havok's x86 static.lib
set_runtimes("MT") -- Prioritizing portability, including C Runtime itself

-- No need to set `set_languages("cxx11")` since C++11 is the default.
target("blender-hkx", function()
	set_languages("cxx17")
	set_pcxxheader("blender-hkx/pch.h") -- Precompiled header
	add_includedirs(
		"blender-hkx",
		"extern/pugixml/src",
		"../Havok SDK/2010_2_0/Source",
		"../Havok SDK/2010_2_0/compat",
		{ public = true }
	)

	add_files("blender-hkx/*.cpp", "extern/pugixml/src/*.cpp")

	add_defines("WIN32", "_CRT_SECURE_NO_DEPRECATE", "_CRT_NONSTDC_NO_DEPRECATE", "_SCL_SECURE_NO_WARNINGS")
	if is_mode("debug") then
		add_defines("_DEBUG", "_CONSOLE")
	else
		add_defines("NDEBUG")
	end

	-- Havok libraries
	if is_mode("debug") then
		add_linkdirs("../Havok SDK/2010_2_0/Lib/win32_net_9-0/debug_multithreaded")
	else
		add_linkdirs("../Havok SDK/2010_2_0/Lib/win32_net_9-0/release_multithreaded")
	end
	add_links({
		"hkaAnimation",
		"hkaInternal",
		"hkaRagdoll",
		"hkBase",
		"hkCompat",
		"hkgBridge",
		"hkgCommon",
		"hkgDx10",
		"hkgDx9",
		"hkgDx9s",
		"hkGeometryUtilities",
		"hkgOgl",
		"hkgOglES",
		"hkgOglES2",
		"hkgOgls",
		"hkInternal",
		"hkpCollide",
		"hkpConstraintSolver",
		"hkpDynamics",
		"hkpInternal",
		"hkpUtilities",
		"hkpVehicle",
		"hkSceneData",
		"hksCommon",
		"hkSerialize",
		"hksXAudio2",
		"hkVisualize",
	})

	-- Old Compatibility
	add_links("oldnames", "legacy_stdio_definitions", "libucrt")
	add_syslinks(
		"advapi32",
		"comdlg32",
		"gdi32",
		"kernel32",
		"odbc32",
		"odbccp32",
		"ole32",
		"oleaut32",
		"shell32",
		"user32",
		"uuid",
		"winspool"
	)
end)
