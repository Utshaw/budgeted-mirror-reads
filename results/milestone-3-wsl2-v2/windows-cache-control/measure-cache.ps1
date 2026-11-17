param(
    [string]$DriveA = 'D',
    [string]$DriveB = 'E',
    [string]$Output = '.\windows-cache-baseline.csv'
)
$ErrorActionPreference = 'Stop'
Add-Type -TypeDefinition @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;
using Microsoft.Win32.SafeHandles;

public static class CacheProbe {
    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)]
    static extern SafeFileHandle CreateFile(string path, uint access, uint share, IntPtr security,
        uint disposition, uint flags, IntPtr template);
    [DllImport("kernel32", SetLastError=true)]
    static extern bool ReadFile(SafeFileHandle file, IntPtr buffer, int length, out int done, IntPtr overlapped);
    [DllImport("kernel32", SetLastError=true)]
    static extern bool SetFilePointerEx(SafeFileHandle file, long offset, out long position, uint origin);
    [DllImport("kernel32", SetLastError=true)]
    static extern IntPtr VirtualAlloc(IntPtr address, UIntPtr size, uint allocation, uint protection);
    [DllImport("kernel32")]
    static extern bool VirtualFree(IntPtr address, UIntPtr size, uint free);
    public static double[] Run(string path, bool bypass, int seed, int count) {
        const int block = 4096;
        int blocks = checked((int)(new System.IO.FileInfo(path).Length / block));
        var rng = new Random(seed);
        var times = new double[count];
        using (var f = CreateFile(path, 0x80000000, 7, IntPtr.Zero, 3,
                bypass ? 0x20000000u : 0u, IntPtr.Zero)) {
            if (f.IsInvalid) throw new Win32Exception();
            IntPtr buf = VirtualAlloc(IntPtr.Zero, new UIntPtr(block), 0x3000, 4);
            if (buf == IntPtr.Zero) throw new Win32Exception();
            try {
                for (int i=0; i<count; i++) {
                    int index = rng.Next(blocks);
                    long offset = (long)index * block;
                    long pos;
                    int got;
                    long start = Stopwatch.GetTimestamp();
                    if (!SetFilePointerEx(f, offset, out pos, 0) ||
                        !ReadFile(f, buf, block, out got, IntPtr.Zero)) throw new Win32Exception();
                    times[i] = (Stopwatch.GetTimestamp()-start) * 1000.0 / Stopwatch.Frequency;
                    if (got != block || Marshal.ReadInt64(buf) != index)
                        throw new Exception("Invalid benchmark record at offset " + offset);
                }
            } finally { VirtualFree(buf, UIntPtr.Zero, 0x8000); }
        }
        return times;
    }
}
'@

$rows = foreach ($drive in $DriveA,$DriveB) {
    $disk = (Get-Partition -DriveLetter $drive).DiskNumber
    $instance = "$disk ${drive}:"
    $counter = [System.Diagnostics.PerformanceCounter]::new('PhysicalDisk','Disk Reads/sec',$instance)
    try {
        foreach ($name in 'mirror','noise') {
            $path = "${drive}:\mirror-reads-wsl2-v2\$name.dat"
            foreach ($repeat in 0..2) {
                $seed = 720 + $repeat
                $count = 512
                # Prime exactly the same offsets with a buffered handle before measuring the pair.
                $null = [CacheProbe]::Run($path,$false,$seed,$count)
                $order = if ($repeat -eq 1) { $true,$false } else { $false,$true }
                foreach ($direct in $order) {
                    $before = $counter.RawValue
                    [double[]]$times = [CacheProbe]::Run($path,$direct,$seed,$count)
                    $reads = $counter.RawValue - $before
                    [Array]::Sort($times)
                    [pscustomobject]@{
                        Drive=$drive; File=$name; Repeat=$repeat; Seed=$seed
                        Mode=if($direct){'unbuffered'}else{'buffered'}
                        Requests=$count; PhysicalDiskReads=$reads
                        MeanMs=($times | Measure-Object -Average).Average
                        P50Ms=$times[[math]::Ceiling(0.50*$count)-1]
                        P99Ms=$times[[math]::Ceiling(0.99*$count)-1]
                    }
                }
            }
        }
    } finally { $counter.Dispose() }
}
$rows | Export-Csv -LiteralPath $Output -NoTypeInformation
