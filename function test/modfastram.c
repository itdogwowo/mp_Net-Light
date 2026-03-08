// modfastram.c
// MicroPython C Module for High Performance RAM VFS
// 
// This module implements a direct memory-mapped file system interface
// to bypass the Python object allocation overhead in memoryview slice assignment.

#include "py/runtime.h"
#include "py/stream.h"
#include "py/mperrno.h"
#include "py/objstr.h"

// File Object Structure
typedef struct _fastram_file_obj_t {
    mp_obj_base_t base;
    uint8_t *buffer;
    size_t buffer_len;
    size_t pos;
    size_t *file_size_ptr; // Pointer to size in FS object
} fastram_file_obj_t;

// FS Object Structure
typedef struct _fastram_fs_obj_t {
    mp_obj_base_t base;
    uint8_t *buffer;
    size_t buffer_len;
    size_t file_size; // Single file support for simplicity
} fastram_fs_obj_t;

// --- File Methods ---

STATIC mp_obj_t fastram_file_write(mp_obj_t self_in, mp_obj_t buf_in) {
    fastram_file_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_buffer_info_t bufinfo;
    mp_get_buffer_raise(buf_in, &bufinfo, MP_BUFFER_READ);

    if (self->pos + bufinfo.len > self->buffer_len) {
        mp_raise_OSError(MP_ENOSPC);
    }

    // Direct memcpy - The fastest way to copy data
    memcpy(self->buffer + self->pos, bufinfo.buf, bufinfo.len);
    self->pos += bufinfo.len;

    if (self->pos > *self->file_size_ptr) {
        *self->file_size_ptr = self->pos;
    }

    return MP_OBJ_NEW_SMALL_INT(bufinfo.len);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_2(fastram_file_write_obj, fastram_file_write);

STATIC mp_obj_t fastram_file_read(size_t n_args, const mp_obj_t *args) {
    fastram_file_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    mp_int_t size = -1;
    if (n_args > 1) {
        size = mp_obj_get_int(args[1]);
    }

    if (size == -1 || self->pos + size > *self->file_size_ptr) {
        size = *self->file_size_ptr - self->pos;
    }
    if (size <= 0) {
        return mp_const_empty_bytes;
    }

    mp_obj_t res = mp_obj_new_bytes(self->buffer + self->pos, size);
    self->pos += size;
    return res;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(fastram_file_read_obj, 1, 2, fastram_file_read);

STATIC mp_obj_t fastram_file_seek(size_t n_args, const mp_obj_t *args) {
    fastram_file_obj_t *self = MP_OBJ_TO_PTR(args[0]);
    mp_int_t offset = mp_obj_get_int(args[1]);
    mp_int_t whence = 0;
    if (n_args > 2) {
        whence = mp_obj_get_int(args[2]);
    }

    switch (whence) {
        case 0: self->pos = offset; break;
        case 1: self->pos += offset; break;
        case 2: self->pos = *self->file_size_ptr + offset; break;
    }

    if (self->pos > *self->file_size_ptr) self->pos = *self->file_size_ptr; // Clamp? Or allow sparse?
    
    return mp_obj_new_int_from_uint(self->pos);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(fastram_file_seek_obj, 2, 3, fastram_file_seek);

STATIC mp_obj_t fastram_file_close(mp_obj_t self_in) {
    return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_1(fastram_file_close_obj, fastram_file_close);

STATIC mp_obj_t fastram_file_enter(mp_obj_t self_in) {
    return self_in;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_1(fastram_file_enter_obj, fastram_file_enter);

STATIC mp_obj_t fastram_file_exit(size_t n_args, const mp_obj_t *args) {
    return mp_const_none;
}
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(fastram_file_exit_obj, 4, 4, fastram_file_exit);

// File locals dict
STATIC const mp_rom_map_elem_t fastram_file_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_write), MP_ROM_PTR(&fastram_file_write_obj) },
    { MP_ROM_QSTR(MP_QSTR_read), MP_ROM_PTR(&fastram_file_read_obj) },
    { MP_ROM_QSTR(MP_QSTR_seek), MP_ROM_PTR(&fastram_file_seek_obj) },
    { MP_ROM_QSTR(MP_QSTR_close), MP_ROM_PTR(&fastram_file_close_obj) },
    { MP_ROM_QSTR(MP_QSTR___enter__), MP_ROM_PTR(&fastram_file_enter_obj) },
    { MP_ROM_QSTR(MP_QSTR___exit__), MP_ROM_PTR(&fastram_file_exit_obj) },
};
STATIC MP_DEFINE_CONST_DICT(fastram_file_locals_dict, fastram_file_locals_dict_table);

// File stream methods
STATIC const mp_stream_p_t fastram_file_stream_p = {
    .read = NULL, // Use locals for now
    .write = NULL,
    .ioctl = NULL,
    .is_text = false,
};

STATIC const mp_obj_type_t fastram_file_type = {
    { &mp_type_type },
    .name = MP_QSTR_FastRamFile,
    .protocol = &fastram_file_stream_p,
    .locals_dict = (mp_obj_dict_t*)&fastram_file_locals_dict,
};

// --- FS Methods ---

STATIC mp_obj_t fastram_fs_make_new(const mp_obj_type_t *type, size_t n_args, size_t n_kw, const mp_obj_t *args) {
    mp_arg_check_num(n_args, n_kw, 1, 1, false);
    size_t size = mp_obj_get_int(args[0]);
    
    fastram_fs_obj_t *self = m_new_obj(fastram_fs_obj_t);
    self->base.type = type;
    self->buffer = m_new(uint8_t, size); // Allocate in GC heap (or use m_new_alloc for PSRAM if configured)
    self->buffer_len = size;
    self->file_size = 0;
    
    return MP_OBJ_FROM_PTR(self);
}

STATIC mp_obj_t fastram_fs_open(mp_obj_t self_in, mp_obj_t path_in, mp_obj_t mode_in) {
    fastram_fs_obj_t *self = MP_OBJ_TO_PTR(self_in);
    const char *mode = mp_obj_str_get_str(mode_in);
    
    if (strchr(mode, 'w') || strchr(mode, 'a')) {
        // Reset for write (simplified single file)
        if (strchr(mode, 'w')) self->file_size = 0;
    }
    
    fastram_file_obj_t *f = m_new_obj(fastram_file_obj_t);
    f->base.type = &fastram_file_type;
    f->buffer = self->buffer;
    f->buffer_len = self->buffer_len;
    f->file_size_ptr = &self->file_size;
    f->pos = 0;
    
    return MP_OBJ_FROM_PTR(f);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_3(fastram_fs_open_obj, fastram_fs_open);

STATIC mp_obj_t fastram_fs_mount(size_t n_args, const mp_obj_t *args) { return mp_const_none; }
STATIC MP_DEFINE_CONST_FUN_OBJ_VAR_BETWEEN(fastram_fs_mount_obj, 2, 3, fastram_fs_mount);

STATIC mp_obj_t fastram_fs_umount(mp_obj_t self_in) { return mp_const_none; }
STATIC MP_DEFINE_CONST_FUN_OBJ_1(fastram_fs_umount_obj, fastram_fs_umount);

STATIC mp_obj_t fastram_fs_stat(mp_obj_t self_in, mp_obj_t path_in) {
    fastram_fs_obj_t *self = MP_OBJ_TO_PTR(self_in);
    mp_obj_t tuple[10] = {
        MP_OBJ_NEW_SMALL_INT(0x8000), // st_mode (file)
        MP_OBJ_NEW_SMALL_INT(0), // st_ino
        MP_OBJ_NEW_SMALL_INT(0), // st_dev
        MP_OBJ_NEW_SMALL_INT(0), // st_nlink
        MP_OBJ_NEW_SMALL_INT(0), // st_uid
        MP_OBJ_NEW_SMALL_INT(0), // st_gid
        mp_obj_new_int_from_uint(self->file_size), // st_size
        MP_OBJ_NEW_SMALL_INT(0), // st_atime
        MP_OBJ_NEW_SMALL_INT(0), // st_mtime
        MP_OBJ_NEW_SMALL_INT(0), // st_ctime
    };
    return mp_obj_new_tuple(10, tuple);
}
STATIC MP_DEFINE_CONST_FUN_OBJ_2(fastram_fs_stat_obj, fastram_fs_stat);

STATIC const mp_rom_map_elem_t fastram_fs_locals_dict_table[] = {
    { MP_ROM_QSTR(MP_QSTR_open), MP_ROM_PTR(&fastram_fs_open_obj) },
    { MP_ROM_QSTR(MP_QSTR_mount), MP_ROM_PTR(&fastram_fs_mount_obj) },
    { MP_ROM_QSTR(MP_QSTR_umount), MP_ROM_PTR(&fastram_fs_umount_obj) },
    { MP_ROM_QSTR(MP_QSTR_stat), MP_ROM_PTR(&fastram_fs_stat_obj) },
    { MP_ROM_QSTR(MP_QSTR_chdir), MP_ROM_PTR(&fastram_fs_mount_obj) }, // Dummy
    { MP_ROM_QSTR(MP_QSTR_getcwd), MP_ROM_PTR(&fastram_fs_mount_obj) }, // Dummy
};
STATIC MP_DEFINE_CONST_DICT(fastram_fs_locals_dict, fastram_fs_locals_dict_table);

const mp_obj_type_t fastram_fs_type = {
    { &mp_type_type },
    .name = MP_QSTR_FastRamFS,
    .make_new = fastram_fs_make_new,
    .locals_dict = (mp_obj_dict_t*)&fastram_fs_locals_dict,
};

// Module globals
STATIC const mp_rom_map_elem_t fastram_module_globals_table[] = {
    { MP_ROM_QSTR(MP_QSTR___name__), MP_ROM_QSTR(MP_QSTR_fastram) },
    { MP_ROM_QSTR(MP_QSTR_FastRamFS), MP_ROM_PTR(&fastram_fs_type) },
};
STATIC MP_DEFINE_CONST_DICT(fastram_module_globals, fastram_module_globals_table);

const mp_obj_module_t fastram_user_cmodule = {
    .base = { &mp_type_module },
    .globals = (mp_obj_dict_t*)&fastram_module_globals,
};

MP_REGISTER_MODULE(MP_QSTR_fastram, fastram_user_cmodule);
