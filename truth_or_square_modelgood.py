import os
import struct
import math
import random
import re
import tkinter as tk
from tkinter import filedialog

# ==========================================
# DEBUG TOGGLES
# ==========================================
FORCE_GEOMETRIC_NORMALS = False
FLIP_ALL_FACES = False  # Set to True if the ENTIRE model renders inside-out

def get_face_normal_unnormalized(v1, v2, v3):
    ux, uy, uz = v2[0] - v1[0], v2[1] - v1[1], v2[2] - v1[2]
    vx, vy, vz = v3[0] - v1[0], v3[1] - v1[1], v3[2] - v1[2]
    return (uy * vz) - (uz * vy), (uz * vx) - (ux * vz), (ux * vy) - (uy * vx)

def extract_materials_regex(data):
    """
    Robust Material Extractor
    Splits the file into property blocks using the 'basic' struct header
    and uses Regex to find the first texture name.
    """
    print("\n[TEXTURE SCANNER] Parsing Material Dictionary...")
    mat_count = struct.unpack_from("<I", data, 124)[0]
    parsed_materials =[]
    
    mat_blocks = data.split(b'basic\x00')[1:]
    
    for m in range(mat_count):
        diff_tex = "Default_Material"
        if m < len(mat_blocks):
            # Regex search for texture extensions
            matches = re.findall(b'([a-zA-Z0-9_.-]+\.(?:rtf))', mat_blocks[m], re.IGNORECASE)
            if matches:
                diff_tex = matches[0].decode('utf-8', 'ignore')
                
        parsed_materials.append(diff_tex)
        print(f" -> Mat {m}: Extracted '{diff_tex}'")
        
    return parsed_materials

def write_obj(filename, vertices, uvs, normals, meshes, materials_tuple):
    base_name = os.path.splitext(os.path.basename(filename))[0]
    mtl_filename = filename.replace(".obj", ".mtl")
    mtl_basename = os.path.basename(mtl_filename)
    written_mats = set()
    
    with open(mtl_filename, "w") as m:
        m.write(f"# Auto-Generated MTL\n\n")
        for mesh in meshes:
            if not mesh["faces"]: continue
            mat_idx = mesh["mat_idx"]
            if mat_idx in written_mats: continue
            written_mats.add(mat_idx)
            
            tex_name = materials_tuple[mat_idx] if mat_idx < len(materials_tuple) else "Default_Material"
            safe_tex_name = os.path.splitext(tex_name)[0]
            mat_name = f"Mat{mat_idx}_{safe_tex_name}"
                
            r, g, b = random.random(), random.random(), random.random()
            m.write(f"newmtl {mat_name}\nKd {r:.4f} {g:.4f} {b:.4f}\nKs 0.0 0.0 0.0\nd 1.0\n") 
            if tex_name != "Default_Material": m.write(f"map_Kd {tex_name}\n")
            m.write("\n")

    with open(filename, "w") as f:
        f.write("# TRUTH OR SQUARE MESH EXPORTER\n")
        f.write(f"mtllib {mtl_basename}\n\n") 
        
        for v in vertices: f.write(f"v {v[0]:.6f} {v[1]:.6f} {v[2]:.6f}\n")
        for uv in uvs: f.write(f"vt {uv[0]:.6f} {1.0 - uv[1]:.6f}\n")
        for n in normals: f.write(f"vn {n[0]:.6f} {n[1]:.6f} {n[2]:.6f}\n")
            
        for idx, mesh in enumerate(meshes):
            if not mesh["faces"]: continue
            
            f.write(f"\ng {mesh['name']}_Submesh{idx}\n")
            
            mat_idx = mesh["mat_idx"]
            tex_name = materials_tuple[mat_idx] if mat_idx < len(materials_tuple) else "Default_Material"
            mat_name = f"Mat{mat_idx}_{os.path.splitext(tex_name)[0]}"
            
            f.write(f"usemtl {mat_name}\ns 1\n")
            for face in mesh["faces"]:
                if FLIP_ALL_FACES:
                    f.write(f"f {face[0]}/{face[0]}/{face[0]} {face[2]}/{face[2]}/{face[2]} {face[1]}/{face[1]}/{face[1]}\n")
                else:
                    f.write(f"f {face[0]}/{face[0]}/{face[0]} {face[1]}/{face[1]}/{face[1]} {face[2]}/{face[2]}/{face[2]}\n")

def main():
    root = tk.Tk()
    root.withdraw()
    file_path = filedialog.askopenfilename(title="Select .msh file", filetypes=[("Mesh", "*.msh")])
    if not file_path: return

    with open(file_path, "rb") as f: data = f.read()
    file_size = len(data)
    out_dir = os.path.dirname(file_path)
    base_name = os.path.splitext(os.path.basename(file_path))[0]
    
    print(f"\n==================================================")
    print(f" HEAVY IRON EXACT PARSER: {base_name}.msh")
    print(f"==================================================")

    total_vertices = struct.unpack_from("<I", data, 8)[0]
    master_pointer = struct.unpack_from("<I", data, 16)[0]
    mesh_type = struct.unpack_from("<H", data, 20)[0]
    submesh_count = struct.unpack_from("<H", data, 22)[0]

    if total_vertices == 0 or file_size < 132: 
        print("[ERROR] File too small.")
        return

    # Extract global scale for Skinned/Type 6 meshes
    try:
        sx, sy, sz = struct.unpack_from("<fff", data, 56)
        scale_x, scale_y, scale_z = sx / 2.0, sy / 2.0, sz / 2.0
    except:
        scale_x = scale_y = scale_z = 1.0

    parsed_materials = extract_materials_regex(data)

    vertices, uvs, raw_normals, raw_positions = [],[], [], []
    geom_normals = [[0.0, 0.0, 0.0] for _ in range(total_vertices)]
    meshes = []

    print("\n[GEOMETRY] Reading Mesh Headers...")
    
    if mesh_type in (2, 5):
        is_type_5 = (mesh_type == 5)
        stride = 16 if is_type_5 else 20
        header_size = 44 if is_type_5 else 60
        curr_off = master_pointer + 120
        
        for m in range(submesh_count):
            try: name = data[curr_off:curr_off+16].split(b'\x00')[0].decode('utf-8', 'ignore') or f"Mesh_{m}"
            except: name = f"Mesh_{m}"
            vert_count = struct.unpack_from("<H", data, curr_off + 26)[0]
            if vert_count == 0 or submesh_count == 1: vert_count = total_vertices
                
            mat_idx = data[curr_off + 20]
            tex_name = parsed_materials[mat_idx] if mat_idx < len(parsed_materials) else "Default_Material"
            print(f" -> Submesh {m} [{name}] -> Mat {mat_idx} [{tex_name}]")
            meshes.append({"name": name, "vert_count": vert_count, "mat_idx": mat_idx, "faces":[]})
            curr_off += header_size
            
        v_pos = curr_off 
        try:
            min_x, min_y, min_z = struct.unpack_from("<fff", data, 28)
            max_x, max_y, max_z = struct.unpack_from("<fff", data, 40)
            cx, cy, cz = (max_x + min_x) / 2.0, (max_y + min_y) / 2.0, (max_z + min_z) / 2.0
            ex, ey, ez = (max_x - min_x) / 2.0, (max_y - min_y) / 2.0, (max_z - min_z) / 2.0
            max_extent = max(ex, ey, ez)
        except: cx = cy = cz = max_extent = 0.0

        is_null_flag =[]
        for _ in range(total_vertices):
            if v_pos + stride > file_size: break
            u, v = struct.unpack_from("<ff", data, v_pos)
            nx, ny, nz = (0, 0, 0) if is_type_5 else struct.unpack_from("<hhh", data, v_pos + 8)
            rx, ry, rz = struct.unpack_from("<hhh", data, v_pos + (10 if is_type_5 else 14))
                
            vertices.append((cx + (rx / 16384.0) * max_extent, cy + (ry / 16384.0) * max_extent, cz + (rz / 16384.0) * max_extent))
            uvs.append((u, v))
            raw_normals.append((nx, ny, nz))
            raw_positions.append((rx, ry, rz))
            
            is_null_flag.append(rx == 0 and ry == 0 and rz == 0 and u == 0.0 and v == 0.0)
            v_pos += stride

        current_vert_idx = 0
        for mesh in meshes:
            start_v = current_vert_idx
            end_v = start_v + mesh["vert_count"]
            if end_v > total_vertices: end_v = total_vertices
            
            strip_index = 0 
            for i in range(start_v, end_v - 2):
                if is_null_flag[i] or is_null_flag[i+1] or is_null_flag[i+2]:
                    strip_index = 0
                    continue
                    
                i1, i2, i3 = (i, i+1, i+2) if strip_index % 2 == 0 else (i, i+2, i+1)
                    
                p1, p2, p3 = raw_positions[i1], raw_positions[i2], raw_positions[i3]
                if p1 == p2 or p2 == p3 or p1 == p3: 
                    strip_index += 1
                    continue

                v1, v2, v3 = vertices[i1], vertices[i2], vertices[i3]
                fnx, fny, fnz = get_face_normal_unnormalized(v1, v2, v3)
                
                geom_normals[i1][0] += fnx; geom_normals[i1][1] += fny; geom_normals[i1][2] += fnz
                geom_normals[i2][0] += fnx; geom_normals[i2][1] += fny; geom_normals[i2][2] += fnz
                geom_normals[i3][0] += fnx; geom_normals[i3][1] += fny; geom_normals[i3][2] += fnz
                mesh["faces"].append((i1+1, i2+1, i3+1))
                
                strip_index += 1
                
            current_vert_idx = end_v

    elif mesh_type == 6:
        curr_off = master_pointer + 120

        for m in range(submesh_count):
            dc_count = struct.unpack_from("<H", data, curr_off + 26)[0]
            try: name = data[curr_off:curr_off+16].split(b'\x00')[0].decode('utf-8', 'ignore') or f"Mesh_{m}"
            except: name = f"Mesh_{m}"
            
            mat_idx = data[curr_off + 20]
            tex_name = parsed_materials[mat_idx] if mat_idx < len(parsed_materials) else "Default_Material"

            print(f" -> Submesh {m}[{name}] -> Bound to Mat {mat_idx} [{tex_name}]")
            meshes.append({"name": name, "dc_count": dc_count, "mat_idx": mat_idx, "draw_calls":[], "faces":[]})
            curr_off += 60

        curr_dc = curr_off
        for m in range(submesh_count):
            for d in range(meshes[m]["dc_count"]):
                start_idx, count = struct.unpack_from("<HH", data, curr_dc)
                meshes[m]["draw_calls"].append({"start": start_idx, "count": count})
                curr_dc += 24

        v_pos = curr_dc

        for _ in range(total_vertices):
            if v_pos + 16 > file_size: break
            u, v = struct.unpack_from("BB", data, v_pos + 5)
            nx, ny, nz = struct.unpack_from("bbb", data, v_pos + 7)
            rx, ry, rz = struct.unpack_from("<hhh", data, v_pos + 10)

            # --- TYPE 6 SCALING APPLIED HERE ---
            vertices.append((
                (rx / 16384.0) * scale_x, 
                (ry / 16384.0) * scale_y, 
                (rz / 16384.0) * scale_z
            ))
            uvs.append((u / 128.0, v / 128.0))
            raw_normals.append((nx, ny, nz))
            v_pos += 16

        for mesh in meshes:
            for dc in mesh["draw_calls"]:
                start = dc["start"]
                count = dc["count"]
                if count < 3 or start + count > total_vertices: continue

                for i in range(count - 2):
                    idx1, idx2, idx3 = start + i, start + i + 1, start + i + 2
                    i1, i2, i3 = (idx1, idx3, idx2) if i % 2 == 1 else (idx1, idx2, idx3)

                    v1, v2, v3 = vertices[i1], vertices[i2], vertices[i3]
                    if v1 == v2 or v2 == v3 or v1 == v3: continue

                    fnx, fny, fnz = get_face_normal_unnormalized(v1, v2, v3)
                    geom_normals[i1][0] += fnx; geom_normals[i1][1] += fny; geom_normals[i1][2] += fnz
                    geom_normals[i2][0] += fnx; geom_normals[i2][1] += fny; geom_normals[i2][2] += fnz
                    geom_normals[i3][0] += fnx; geom_normals[i3][1] += fny; geom_normals[i3][2] += fnz

                    mesh["faces"].append((i1+1, i2+1, i3+1))

    normals =[]
    for i in range(len(vertices)):
        nx, ny, nz = raw_normals[i]
        gnx, gny, gnz = geom_normals[i]
        
        if FORCE_GEOMETRIC_NORMALS:
            nx, ny, nz = gnx, gny, gnz
        else:
            if mesh_type in (2, 6):
                # Fixing the normal sign based on bottom limits of bit-sizes
                if nx in (-128, -16384, -32768): nx = abs(nx)-1 if gnx > 0 else nx
                if ny in (-128, -16384, -32768): ny = abs(ny)-1 if gny > 0 else ny
                if nz in (-128, -16384, -32768): nz = abs(nz)-1 if gnz > 0 else nz

        length = math.sqrt(nx*nx + ny*ny + nz*nz)
        if length > 0.1: 
            normals.append((nx/length, ny/length, nz/length))
        else: 
            # TYPE 5 FALLBACK - Restores the uniform 'unlit' shader illusion
            normals.append((0.0, 1.0, 0.0))

    out_file = os.path.join(out_dir, f"{base_name}_Textured.obj")
    write_obj(out_file, vertices, uvs, normals, meshes, parsed_materials)
    print(f"\n[SUCCESS] Exported '{os.path.basename(out_file)}'")

if __name__ == "__main__":
    try: main()
    except Exception as e:
        import traceback
        traceback.print_exc()
    input("\nPress Enter to exit...")