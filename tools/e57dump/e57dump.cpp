// SPDX-License-Identifier: GPL-3.0-or-later
// E57 point-cloud bridge (D148): read every Data3D scan with libe57format and write a tiny binary
// stream to stdout: uint64 point count, then count * (float32 x, y, z), metres. `--write-simple PATH`
// writes a three-point E57 fixture for the tests. Errors go to stderr with a non-zero exit.
#include <E57Format/E57SimpleReader.h>
#include <E57Format/E57SimpleWriter.h>

#include <cstdint>
#include <cstdio>
#include <cstring>
#include <exception>
#include <iostream>
#include <string>
#include <vector>

#ifdef _WIN32
#include <fcntl.h>
#include <io.h>
#endif

namespace {

void write_points(const std::vector<float>& x, const std::vector<float>& y,
                  const std::vector<float>& z)
{
    std::vector<float> row;
    row.reserve(3 * x.size());
    for (size_t i = 0; i < x.size(); ++i) {
        row.push_back(x[i]);
        row.push_back(y[i]);
        row.push_back(z[i]);
    }
    std::fwrite(row.data(), sizeof(float), row.size(), stdout);
}

int write_fixture(const char* path)
{
    e57::Writer writer(path, e57::WriterOptions{});
    e57::Data3D header;
    header.pointCount = 3;
    header.pointFields.cartesianXField = true;
    header.pointFields.cartesianYField = true;
    header.pointFields.cartesianZField = true;
    std::vector<float> x{0.0f, 1.0f, 0.0f}, y{0.0f, 0.0f, 1.0f}, z{0.0f, 0.0f, 0.0f};
    e57::Data3DPointsFloat buffers;
    buffers.cartesianX = x.data();
    buffers.cartesianY = y.data();
    buffers.cartesianZ = z.data();
    writer.WriteData3DData(header, buffers);
    writer.Close();
    return 0;
}

int dump(const char* path)
{
    e57::Reader reader(path, e57::ReaderOptions{});
    const int64_t scans = reader.GetData3DCount();
    uint64_t total = 0;
    for (int64_t i = 0; i < scans; ++i) {
        e57::Data3D header;
        reader.ReadData3D(i, header);
        total += static_cast<uint64_t>(header.pointCount);
    }
    std::fwrite(&total, sizeof(uint64_t), 1, stdout);
    for (int64_t i = 0; i < scans; ++i) {
        e57::Data3D header;
        reader.ReadData3D(i, header);
        const size_t n = header.pointCount;
        if (!n)
            continue;
        std::vector<float> x(n), y(n), z(n);
        std::vector<int8_t> invalid(n, 0);
        e57::Data3DPointsFloat buffers;
        buffers.cartesianX = x.data();
        buffers.cartesianY = y.data();
        buffers.cartesianZ = z.data();
        buffers.cartesianInvalidState = invalid.data();
        e57::CompressedVectorReader vector = reader.SetUpData3DPointsData(i, n, buffers);
        while (unsigned got = vector.read())
            write_points(x, y, z);
        vector.close();
    }
    reader.Close();
    return 0;
}

} // namespace

int main(int argc, char** argv)
{
#ifdef _WIN32
    _setmode(_fileno(stdout), _O_BINARY);
#endif
    try {
        if (argc == 3 && std::strcmp(argv[1], "--write-simple") == 0)
            return write_fixture(argv[2]);
        if (argc == 2)
            return dump(argv[1]);
        std::cerr << "usage: e57dump FILE.e57 | e57dump --write-simple OUT.e57\n";
        return 2;
    } catch (const e57::E57Exception& ex) {
        std::cerr << "e57dump: " << ex.what() << "\n";
        return 1;
    } catch (const std::exception& ex) {
        std::cerr << "e57dump: " << ex.what() << "\n";
        return 1;
    }
}
