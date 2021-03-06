import numpy as np
import os
import sys
import random

testing = False
#Which method to use for determining plane coefficients
# 0 - Ground truth points
# 1 - RANSAC
use_ground_points = 0
ransac = 1
plane_method = 0

specific_idx = -1

def main():
    base_dir = os.path.expanduser('~') + '/GTAData/object/training/'
    velo_dir = base_dir + 'velodyne'
    plane_dir = base_dir + 'planes'
    if plane_method == 1:
        plane_dir = plane_dir + '_ransac'
    ground_points_dir = base_dir + 'ground_points'
    grid_points_dir = base_dir + 'ground_points_grid'
    files = os.listdir(velo_dir)
    num_files = len(files)
    file_idx = 0

    if not os.path.exists(plane_dir):
        os.makedirs(plane_dir)

    for file in files:
        filepath = velo_dir + '/' + file

        idx = int(os.path.splitext(file)[0])
        if specific_idx != -1:
            idx = specific_idx
        planes_file = plane_dir + '/%06d.txt' % idx

        x,y,z,i = read_lidar(filepath)
        all_points = np.vstack((-y, -z, x)).T

        # Remove nan points
        nan_mask = ~np.any(np.isnan(all_points), axis=1)
        point_cloud = all_points[nan_mask].T

        ground_points_failed = False
        if plane_method == use_ground_points:
            s = loadGroundPointsFromFile(idx, ground_points_dir, grid_points_dir)
            if s.shape[0] < 4:
                print("Not enough points at idx: ", idx)
                ground_points_failed = True
            else:
                m = estimate(s)
                a, b, c, d = m
        
        if plane_method == ransac or ground_points_failed:
            points = point_cloud.T
            all_points_near = points[
                (points[:, 0] > -3.0) &
                (points[:, 0] < 3.0) &
                (points[:, 1] > -3.0) &
                (points[:, 1] < 0.0) &
                (points[:, 2] < 10.0) &
                (points[:, 2] > 2.0)]
            n = all_points_near.shape[0]
            max_iterations = 100
            goal_inliers = n * 0.5
            m, b = run_ransac(all_points_near, lambda x, y: is_inlier(x, y, 0.2), 3, goal_inliers, max_iterations)
            a, b, c, d = m

        with open(planes_file, 'w+') as f:
            f.write('# Plane\nWidth 4\nHeight 1\n')
            if plane_method == ransac or plane_method == use_ground_points:
                coeff_string = '%.6e %.6e %.6e %.6e' % (a,b,c,d)
            else:
                coeff_string = '%.6e %.6e %.6e %.6e' % (plane_coeffs[0], plane_coeffs[1], plane_coeffs[2], plane_coeffs[3])
            #print(coeff_string)
            f.write(coeff_string)

        sys.stdout.write("\rGenerating plane {} / {}".format(
            file_idx + 1, num_files))
        sys.stdout.flush()
        file_idx = file_idx + 1

        if testing and idx == 2 or specific_idx != -1:
            quit()
    

def loadGroundPointsFromFile(idx, ground_points_dir, grid_points_dir):
    file = ground_points_dir + '/%06d.txt' % idx
    p = np.loadtxt(file, delimiter=',',
                       dtype=float,
                       usecols=np.arange(start=0, step=1, stop=3))

    x = p[:,0]
    y = p[:,1]
    z = p[:,2]

    valid_mask = z > -5
    use_extra_points = np.sum(valid_mask) <= 4
    if use_extra_points:
        extra_points = loadPointsFromGrid(idx, grid_points_dir, valid_mask, x, y)

    x = x[valid_mask]
    y = y[valid_mask]
    z = z[valid_mask]
    all_points = np.vstack((y, -z, x)).T

    print(all_points)
    if use_extra_points:
        all_points = np.vstack((all_points,extra_points))
    return all_points

def loadPointsFromGrid(idx, grid_points_dir, valid_mask, x, y):
    file = grid_points_dir + '/%06d.txt' % idx
    p = np.loadtxt(file, delimiter=',',
                       dtype=float,
                       usecols=np.arange(start=0, step=1, stop=3))

    #Shrink to only contain points within smaller grid in front of vehicle
    x = p[:,0]
    y = p[:,1]
    z = p[:,2]

    #x is forward here, y is right, z is up
    mask = (x > 0) & (x < 40)
    x = x[mask]
    y = y[mask]
    z = z[mask]

    mask = (y > -15) & (y < 15)
    x = x[mask]
    y = y[mask]
    z = z[mask]

    mask = z > -5
    x = x[mask]
    y = y[mask]
    z = z[mask]

    #mask = valid_mask == False
    #x = x[mask].astype(int)
    #y = y[mask].astype(int)

    points = np.vstack((y, -z, x)).T
    np.set_printoptions(suppress=True)
    print(points)

    return points


def getGridIndex(x,y):
    max_dist = 120
    interval = 2
    row = (2*max_dist)/2 + 1
    idx = max_dist + x/interval + (y/interval + 1)*row
    print("x: ", x, " y: ", y, " idx: ", idx)
    return idx

def read_lidar(filepath):
    """Reads in PointCloud from Kitti Dataset.
        Keyword Arguments:
        ------------------
        velo_dir : Str
                    Directory of the velodyne files.
        img_idx : Int
                  Index of the image.
        Returns:
        --------
        x : Numpy Array
                   Contains the x coordinates of the pointcloud.
        y : Numpy Array
                   Contains the y coordinates of the pointcloud.
        z : Numpy Array
                   Contains the z coordinates of the pointcloud.
        i : Numpy Array
                   Contains the intensity values of the pointcloud.
        [] : if file is not found
        """

    if os.path.exists(filepath):
        with open(filepath, 'rb') as fid:
            data_array = np.fromfile(fid, np.single)

        xyzi = data_array.reshape(-1, 4)

        x = xyzi[:, 0]
        y = xyzi[:, 1]
        z = xyzi[:, 2]
        i = xyzi[:, 3]

        return x, y, z, i
    else:
        return []


def estimate_ground_plane(point_cloud):
    """Estimates a ground plane by subsampling 2048 points in an area in front
    of the car, and running a least squares fit of a plane on the lowest
    points along y.
    Args:
        point_cloud: point cloud (3, N)
    Returns:
        ground_plane: ground plane coefficients
    """

    if len(point_cloud) == 0:
        raise ValueError('Lidar points are completely empty')

    # Subsamples points in from of the car, 10m across and 30m in depth
    points = point_cloud.T
    all_points_near = points[
        (points[:, 0] > -5.0) &
        (points[:, 0] < 5.0) &
        (points[:, 2] < 30.0) &
        (points[:, 2] > 2.0)]

    if len(all_points_near) == 0:
        raise ValueError('No Lidar points in this frame')

    # Subsample near points
    subsample_num_near = 2048
    near_indices = np.random.randint(0, len(all_points_near),
                                     subsample_num_near)
    points_subsampled = all_points_near[near_indices]

    # Split into distance bins
    all_points_in_bins = []
    all_cropped_points = []
    for dist_bin_idx in range(3):
        points_in_bin = points_subsampled[
            (points_subsampled[:, 2] > dist_bin_idx * 10.0) &
            (points_subsampled[:, 2] < (dist_bin_idx + 1) * 10.0)]

        # Save to points in bins
        all_points_in_bins.extend(points_in_bin)

        # Sort by y for cropping
        # sort_start_time = time.time()
        y_order = np.argsort(points_in_bin[:, 1])
        # print('sort', time.time() - sort_start_time)

        # Crop each bin
        num_points_in_bin = len(points_in_bin)
        # crop_start_time = time.time()

        crop_indices = np.array([int(num_points_in_bin * 0.90),
                                 int(num_points_in_bin * 0.98)])
        points_cropped = points_in_bin[
            y_order[crop_indices[0]:crop_indices[1]]]
        # print('crop', time.time() - crop_start_time)

        all_cropped_points.extend(points_cropped)
    all_cropped_points = np.asarray(all_cropped_points)

    # Do least squares fit to get ground plane coefficients
    ground_plane = estimate_plane_coeffs(all_cropped_points)

    return ground_plane

########################
#RANSAC code from: https://github.com/falcondai/py-ransac
########################
def augment(xyzs):
    axyz = np.ones((len(xyzs), 4))
    axyz[:, :3] = xyzs
    return axyz

def estimate(xyzs):
    axyz = augment(xyzs[:])
    #print(axyz)
    #print(np.linalg.svd(axyz)[-1][-1, :])
    return np.linalg.svd(axyz)[-1][-1, :]

def is_inlier(coeffs, xyz, threshold):
    return np.abs(coeffs.dot(augment([xyz]).T)) < threshold

def run_ransac(data, is_inlier, sample_size, goal_inliers, max_iterations, stop_at_goal=True, random_seed=None):
    best_ic = 0
    best_model = None
    random.seed(random_seed)
    # random.sample cannot deal with "data" being a numpy array
    data = list(data)
    for i in range(max_iterations):
        s = random.sample(data, int(sample_size))
        m = estimate(s)
        ic = 0
        for j in range(len(data)):
            if is_inlier(m, data[j]):
                ic += 1

        #print(s)
        #print('estimate:', m,)
        #print('# inliers:', ic)

        if ic > best_ic:
            best_ic = ic
            best_model = m
            if ic > goal_inliers and stop_at_goal:
                break
    print('took iterations:', i+1, 'best model:', best_model, 'explains:', best_ic)
    return best_model, best_ic

main()