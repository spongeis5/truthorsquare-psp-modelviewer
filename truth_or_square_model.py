import os
import struct
import math
import random
import re
import tkinter as tk
from tkinter import filedialog
from collections import defaultdict

# ==========================================
# DEBUG TOGGLES
# ==========================================
FLIP_ALL_FACES = False   # set True if a model renders inside-out
COLOR_FORMAT   = "4444"  # vertex color decode for Type 5 (change if your viewer used 5650/5551)

def decode_psp_color(color_int, fmt="4444"):
    if fmt == "4444":
        return (( color_int        & 0x0F) / 15.0,
                ((color_int >> 4)   & 0x0F) / 15.0,
                ((color_int >> 8)   & 0x0F) / 15.0,
                ((color_int >> 12)  & 0x0F) / 15.0)
    if fmt == "5650":  # RGB565
        return (( color_int        & 0x1F) / 31.0,
                ((color_int >> 5)   & 0x3F) / 63.0,
                ((color_int >> 11)  & 0x1F) / 31.0, 1.0)
    if fmt == "5551":  # RGBA5551 (PSP order: A is high bit)
        return (( color_int        & 0x1F) / 31.0,
                ((color_int >> 5)   & 0x1F) / 31.0,
                ((color_int >> 10)  & 0x1F) / 31.0,
                 1.0 if (color_int >> 15) & 1 else 0.0)
    return (1.0, 1.0, 1.0, 1.0)

def get_face_normal_unnormalized(v1, v2, v3):
    ux, uy, uz = v2[0]-v1[0], v2[1]-v1[1], v2[2]-v1[2]
    vx, vy, vz = v3[0]-v1[0], v3[1]-v1[1], v3[2]-v1[2]
    return (uy*vz - uz*vy, uz*vx - ux*vz, ux*vy - uy*vx)

def extract_materials_regex(data):
    print("\n[TEXTURE SCANNER] Parsing Material Dictionary...")
    try:
        mat_count = struct.unpack_from("<I", data, 124)[0]
    except Exception:
        mat_count = 0
    parsed = []
    mat_blocks = data.split(b'basic\x00')[1:]
    for m in range(mat_count):
        diff_tex = "Default_Material"
        if m < len(mat_blocks):
            matches = re.findall(rb'([a-zA-Z0-9_.-]+\.(?:rtf))', mat_blocks[m], re.IGNORECASE)
            if matches:
                diff_tex = matches[0].decode('utf-8', 'ignore')
        parsed.append(diff_tex)
        print(f" -> Mat {m}: '{diff_tex}'")
    return parsed

def write_obj(filename, vertices, uvs, normals, colors, meshes, materials_tuple):
    mtl_filename = filename.replace(".obj", ".mtl")
    mtl_basename = os.path.basename(mtl_filename)
    written = set()

    with open(mtl_filename, "w") as m:
        m.write("# Auto-Generated MTL\n\n")
        for mesh in meshes:
            if not mesh["faces"]: continue
            mat_idx = mesh["mat_idx"]
            if mat_idx in written: continue
            written.add(mat_idx)
            tex = materials_tuple[mat_idx] if mat_idx < len(materials_tuple) else "Default_Material"
            mat_name = f"Mat{mat_idx}_{os.path.splitext(tex)[0]}"
            r, g, b = random.random(), random.random(), random.random()
            m.write(f"newmtl {mat_name}\nKd {r:.4f} {g:.4f} {b:.4f}\nKs 0.0 0.0 0.0\nd 1.0\n")
            if tex != "Default_Material":
                m.write(f"map_Kd {tex}\n")
            m.write("\n")

    with open(filename, "w") as f:
        f.write("# TRUTH OR SQUARE MESH EXPORTER\n")
        f.write(f"mtllib {mtl_basename}\n\n")
        for i, v in enumerate(vertices):
            c = colors[i] if i < len(colors) else (1.0, 1.0, 1.0, 1.0)
            f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f} {c[0]:.4f} {c[1]:.4f} {c[2]:.4f}\n")
        for uv in uvs:
            f.write(f"vt {uv[0]:.6f} {1.0 - uv[1]:.6f}\n")
        for n in normals:
            f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")

        for idx, mesh in enumerate(meshes):
            if not mesh["faces"]: continue
            f.write(f"\ng {mesh['name']}_Submesh{idx}\n")
            mat_idx = mesh["mat_idx"]
            tex = materials_tuple[mat_idx] if mat_idx < len(materials_tuple) else "Default_Material"
            f.write(f"usemtl Mat{mat_idx}_{os.path.splitext(tex)[0]}\ns 1\n")
            for face in mesh["faces"]:
                a, b, c = face
                if FLIP_ALL_FACES:
                    a, b, c = a, c, b
                f.write(f"f {a}/{a}/{a} {b}/{b}/{b} {c}/{c}/{c}\n")

def main():
    root = tk.Tk(); root.withdraw()
    file_path = filedialog.askopenfilename(title="Select .msh file", filetypes=[("Mesh", "*.msh")])
    if not file_path: return

    with open(file_path, "rb") as f:
        data = f.read()
    file_size = len(data)
    out_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]

    print(f"\n==================================================")
    print(f" TRUTH OR SQUARE PARSER: {base_name}.msh")
    print(f"==================================================")

    total_vertices = struct.unpack_from("<I", data, 8)[0]
    master_pointer = struct.unpack_from("<I", data, 16)[0]
    mesh_type      = struct.unpack_from("<H", data, 20)[0]
    submesh_count  = struct.unpack_from("<H", data, 22)[0]

    if total_vertices == 0 or file_size < 132:
        print("[ERROR] File too small / no vertices."); return

    try:
        sx, sy, sz = struct.unpack_from("<fff", data, 56)
        scale_x, scale_y, scale_z = sx/2.0, sy/2.0, sz/2.0
    except Exception:
        scale_x = scale_y = scale_z = 1.0

    parsed_materials = extract_materials_regex(data)
    vertices, uvs, raw_normals, raw_positions, colors = [], [], [], [], []
    geom_normals = [[0.0, 0.0, 0.0] for _ in range(total_vertices)]
    meshes = []

    print(f"\n[GEOMETRY] mesh_type = {mesh_type}, submeshes = {submesh_count}, verts = {total_vertices}")

    # =========================================================
    # TYPE 2 : sequential triangle strips (16-bit pos, normals)
    # =========================================================
    if mesh_type == 2:
        stride = 20
        header_size = 60
        curr_off = master_pointer + 120

        current_vert_idx = 0
        for m in range(submesh_count):
            name = data[curr_off:curr_off+16].split(b'\x00')[0].decode('utf-8', 'ignore') or f"Mesh_{m}"
            mat_idx = data[curr_off + 20]
            raw_count = struct.unpack_from("<H", data, curr_off + 26)[0]
            vert_count = total_vertices if (raw_count == 0 or submesh_count == 1) else raw_count
            start_v = current_vert_idx
            end_v = min(start_v + vert_count, total_vertices)
            print(f" -> Submesh {m} [{name}] verts {start_v}..{end_v}, Mat {mat_idx}")
            meshes.append({"name": name, "start": start_v, "count": end_v - start_v,
                           "mat_idx": mat_idx, "faces": []})
            current_vert_idx = end_v
            curr_off += header_size

        v_pos = curr_off
        try:
            min_x, min_y, min_z = struct.unpack_from("<fff", data, 28)
            max_x, max_y, max_z = struct.unpack_from("<fff", data, 40)
            cx, cy, cz = (max_x+min_x)/2, (max_y+min_y)/2, (max_z+min_z)/2
            ex, ey, ez = (max_x-min_x)/2, (max_y-min_y)/2, (max_z-min_z)/2
            max_extent = max(ex, ey, ez)
        except Exception:
            cx = cy = cz = max_extent = 0.0

        is_null = []
        for _ in range(total_vertices):
            if v_pos + stride > file_size: break
            u, v = struct.unpack_from("<ff", data, v_pos)
            nx, ny, nz = struct.unpack_from("<hhh", data, v_pos + 8)
            rx, ry, rz = struct.unpack_from("<hhh", data, v_pos + 14)
            vertices.append((cx + (rx/16384.0)*max_extent,
                             cy + (ry/16384.0)*max_extent,
                             cz + (rz/16384.0)*max_extent))
            uvs.append((u, v))
            colors.append((1.0, 1.0, 1.0, 1.0))
            raw_normals.append((nx, ny, nz))
            raw_positions.append((rx, ry, rz))
            is_null.append(rx == 0 and ry == 0 and rz == 0 and u == 0.0 and v == 0.0)
            v_pos += stride

        for mesh in meshes:
            start_v, count = mesh["start"], mesh["count"]
            if count < 3: continue
            for local_i in range(count - 2):
                i1, i2, i3 = start_v+local_i, start_v+local_i+1, start_v+local_i+2
                f1, f2, f3 = (i1, i3, i2) if local_i % 2 == 1 else (i1, i2, i3)
                if is_null[f1] or is_null[f2] or is_null[f3]: continue
                p1, p2, p3 = raw_positions[f1], raw_positions[f2], raw_positions[f3]
                if p1 == p2 or p2 == p3 or p1 == p3: continue
                v1, v2, v3 = vertices[f1], vertices[f2], vertices[f3]
                if v1 == v2 or v2 == v3 or v1 == v3: continue
                mesh["faces"].append((f1+1, f2+1, f3+1))
                fnx, fny, fnz = get_face_normal_unnormalized(v1, v2, v3)
                for vi in (f1, f2, f3):
                    geom_normals[vi][0]+=fnx; geom_normals[vi][1]+=fny; geom_normals[vi][2]+=fnz

    # =========================================================
    # TYPE 5 : environment
    # =========================================================
    elif mesh_type == 5:
        stride = 16
        header_size = 60
        curr_off = master_pointer + 120

        min_x, min_y, min_z = struct.unpack_from("<fff", data, 28)
        max_x, max_y, max_z = struct.unpack_from("<fff", data, 40)
        cx, cy, cz = (max_x+min_x)/2, (max_y+min_y)/2, (max_z+min_z)/2
        ex, ey, ez = (max_x-min_x)/2, (max_y-min_y)/2, (max_z-min_z)/2
        max_extent = max(ex, ey, ez)

        # submesh table: name@0, mat@20, start_vertex@24, vertex_count@26
        for m in range(submesh_count):
            name = data[curr_off:curr_off+16].split(b'\x00')[0].decode('utf-8', 'ignore') or f"Mesh_{m}"
            mat_idx = data[curr_off + 20]
            start_v = struct.unpack_from("<H", data, curr_off + 24)[0]
            vcount  = struct.unpack_from("<H", data, curr_off + 26)[0]
            print(f" -> Submesh {m} [{name}] verts {start_v}..{start_v+vcount}, Mat {mat_idx}")
            meshes.append({"name": name, "start": start_v, "count": vcount,
                           "mat_idx": mat_idx, "faces": []})
            curr_off += header_size

        # vertex buffer
        v_pos = curr_off
        is_null = []
        for _ in range(total_vertices):
            if v_pos + stride > file_size: break
            u, v = struct.unpack_from("<ff", data, v_pos)
            color_int = struct.unpack_from("<H", data, v_pos + 8)[0]
            rx, ry, rz = struct.unpack_from("<hhh", data, v_pos + 10)
            vertices.append((cx + (rx/16384.0)*max_extent,
                             cy + (ry/16384.0)*max_extent,
                             cz + (rz/16384.0)*max_extent))
            uvs.append((u, v))
            colors.append(decode_psp_color(color_int, COLOR_FORMAT))
            raw_normals.append((0, 0, 0))
            raw_positions.append((rx, ry, rz))
            is_null.append(rx == 0 and ry == 0 and rz == 0 and u == 0.0 and v == 0.0)
            v_pos += stride

        # stitched triangle strips, per submesh vertex range
        for mesh in meshes:
            start_v = mesh["start"]
            end_v = min(start_v + mesh["count"], total_vertices)
            for i in range(start_v, end_v - 2):
                local_i = i - start_v
                f1, f2, f3 = (i, i+2, i+1) if local_i % 2 == 1 else (i, i+1, i+2)
                if is_null[f1] or is_null[f2] or is_null[f3]:
                    continue
                p1, p2, p3 = raw_positions[f1], raw_positions[f2], raw_positions[f3]
                if p1 == p2 or p2 == p3 or p1 == p3:   # cull strip-stitch / degenerate
                    continue
                mesh["faces"].append((f1+1, f2+1, f3+1))
                v1, v2, v3 = vertices[f1], vertices[f2], vertices[f3]
                fnx, fny, fnz = get_face_normal_unnormalized(v1, v2, v3)
                for vi in (f1, f2, f3):
                    geom_normals[vi][0]+=fnx; geom_normals[vi][1]+=fny; geom_normals[vi][2]+=fnz

    # =========================================================
    # TYPE 6 : skinned, draw-call strips (8-bit pos/normals)
    # =========================================================
    elif mesh_type == 6:
        curr_off = master_pointer + 120
        for m in range(submesh_count):
            dc_count = struct.unpack_from("<H", data, curr_off + 26)[0]
            name = data[curr_off:curr_off+16].split(b'\x00')[0].decode('utf-8', 'ignore') or f"Mesh_{m}"
            mat_idx = data[curr_off + 20]
            print(f" -> Submesh {m} [{name}] draw_calls {dc_count}, Mat {mat_idx}")
            meshes.append({"name": name, "dc_count": dc_count, "mat_idx": mat_idx,
                           "draw_calls": [], "faces": []})
            curr_off += 60

        curr_dc = curr_off
        for m in range(submesh_count):
            for _ in range(meshes[m]["dc_count"]):
                start_idx, count = struct.unpack_from("<HH", data, curr_dc)
                meshes[m]["draw_calls"].append({"start": start_idx, "count": count})
                curr_dc += 24

        v_pos = curr_dc
        for _ in range(total_vertices):
            if v_pos + 16 > file_size: break
            u, v = struct.unpack_from("BB", data, v_pos + 5)
            nx, ny, nz = struct.unpack_from("bbb", data, v_pos + 7)
            rx, ry, rz = struct.unpack_from("<hhh", data, v_pos + 10)
            vertices.append(((rx/16384.0)*scale_x, (ry/16384.0)*scale_y, (rz/16384.0)*scale_z))
            uvs.append((u/128.0, v/128.0))
            colors.append((1.0, 1.0, 1.0, 1.0))
            raw_normals.append((nx, ny, nz))
            v_pos += 16

        for mesh in meshes:
            for dc in mesh["draw_calls"]:
                start, count = dc["start"], dc["count"]
                if count < 3 or start + count > total_vertices: continue
                for local_i in range(count - 2):
                    i1, i2, i3 = start+local_i, start+local_i+1, start+local_i+2
                    f1, f2, f3 = (i1, i3, i2) if local_i % 2 == 1 else (i1, i2, i3)
                    v1, v2, v3 = vertices[f1], vertices[f2], vertices[f3]
                    if v1 == v2 or v2 == v3 or v1 == v3: continue
                    mesh["faces"].append((f1+1, f2+1, f3+1))
                    fnx, fny, fnz = get_face_normal_unnormalized(v1, v2, v3)
                    for vi in (f1, f2, f3):
                        geom_normals[vi][0]+=fnx; geom_normals[vi][1]+=fny; geom_normals[vi][2]+=fnz
    else:
        print(f"[ERROR] Unsupported mesh_type {mesh_type}")
        return

    # =========================================================
    # NORMALS
    # =========================================================
    # For Type 5 (and any geometry-only path) we smooth across split/duplicate
    # vertices that share a position, so strip seams shade smoothly without
    # having to Merge-by-Distance (which would damage UVs / vertex colors).
    pos_norm = defaultdict(lambda: [0.0, 0.0, 0.0])
    for i in range(len(vertices)):
        k = (round(vertices[i][0], 4), round(vertices[i][1], 4), round(vertices[i][2], 4))
        gx, gy, gz = geom_normals[i]
        acc = pos_norm[k]
        acc[0] += gx; acc[1] += gy; acc[2] += gz

    normals = []
    for i in range(len(vertices)):
        if mesh_type == 5:
            # environments have no stored normals -> use smoothed geometric
            k = (round(vertices[i][0], 4), round(vertices[i][1], 4), round(vertices[i][2], 4))
            gnx, gny, gnz = pos_norm[k]
            length = math.sqrt(gnx*gnx + gny*gny + gnz*gnz)
            normals.append((gnx/length, gny/length, gnz/length) if length > 1e-6 else (0.0, 1.0, 0.0))
        else:
            gnx, gny, gnz = geom_normals[i]
            nx, ny, nz = raw_normals[i]
            if nx in (-128, -16384, -32768): nx = abs(nx)-1 if gnx > 0 else nx
            if ny in (-128, -16384, -32768): ny = abs(ny)-1 if gny > 0 else ny
            if nz in (-128, -16384, -32768): nz = abs(nz)-1 if gnz > 0 else nz
            length = math.sqrt(nx*nx + ny*ny + nz*nz)
            normals.append((nx/length, ny/length, nz/length) if length > 0.1 else (0.0, 1.0, 0.0))

    out_file = os.path.join(out_dir, f"{base_name}_Final.obj")
    write_obj(out_file, vertices, uvs, normals, colors, meshes, parsed_materials)
    total_faces = sum(len(m["faces"]) for m in meshes)
    print(f"\n[SUCCESS] Exported '{os.path.basename(out_file)}'  ({total_faces} faces)")

if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc()
    input("\nPress Enter to exit...")
