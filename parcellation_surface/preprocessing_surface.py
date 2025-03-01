"""
Module Name: preprocessing_surface.py
Description:
    This script is used to load and process volume and surface data from Freesurfer outputs.
    It includes utilities for:
      - Loading and preprocessing fMRI volume data
      - Projecting fMRI volume data onto the cortical surface
      - Converting fMRI volume data to spatial modes using SVD

Author: Robin Junod, robin.junod@epfl.ch
Created: 2025-01-16

"""
#%%
import os
import numpy as np
import nibabel as nib
from datetime import datetime
from nilearn import surface
from nilearn.image import resample_img

def load_data_normalized(surf_fmri_path,
                         vol_fmri_path, 
                         brain_mask_path):
    """
    Load and normalize surface and volume fMRI data.

    Args:
        surf_fmri_path (str): Path to the surface fMRI data file.
        vol_fmri_path (str): Path to the volume fMRI data file.
        brain_mask_path (str): Path to the brain mask file.

    Returns:
        tuple: A tuple containing:
            - surf_fmri_n (numpy.ndarray): Normalized surface fMRI data.
            - vol_fmri_n (numpy.ndarray): Normalized volume fMRI data.
    """
    # Load the surface data
    surf_fmri = nib.load(str(surf_fmri_path)).get_fdata().squeeze()
    surf_fmri_n = (surf_fmri - np.mean(surf_fmri, axis=1, keepdims=True)) / np.std(surf_fmri, axis=1, keepdims=True)
    
    # Load the images using nibabel
    vol_fmri = nib.load(str(vol_fmri_path))
    mask_img = nib.load(brain_mask_path)

    # resample the mask to the right one
    mask_img = resample_img(
        mask_img,
        target_affine=vol_fmri.affine,
        target_shape=vol_fmri.get_fdata().shape[:-1],
        interpolation='nearest',
        force_resample=True
    )

    fmri_data = vol_fmri.get_fdata()
    mask_data = mask_img.get_fdata().astype(bool)  # Convert mask to boolean
    # Normalize the data
    vol_fmri = fmri_data[mask_data] 
    vol_fmri_n = (vol_fmri - np.mean(vol_fmri, axis=1, keepdims=True)) / np.std(vol_fmri, axis=1, keepdims=True)
    
    # Remove nans from the data
    surf_fmri_n = np.nan_to_num(surf_fmri_n).astype(np.float32)
    vol_fmri_n = np.nan_to_num(vol_fmri_n).astype(np.float32)
    return surf_fmri_n, vol_fmri_n



def load_volume_data(path_func, path_brain_mask):
    """
    Load and preprocess fMRI volume data and brain mask.
    
    Args:
        path_func (str): Path to the fMRI volume data file.
        path_brain_mask (str): Path to the brain mask file.

    Returns:
        tuple: A tuple containing:
            - vol_fmri_masked (numpy.ndarray): Masked fMRI volume data.
            - resampled_mask (numpy.ndarray): Resampled brain mask.
            - affine_vol_fmri (numpy.ndarray): Affine transformation matrix of the fMRI volume data.
    """
    # Load volumetric data
    fmri_img = nib.load(path_func)
    affine_vol_fmri = fmri_img.affine
    vol_fmri = fmri_img.get_fdata()

    # Load mask data (and resample to target shape)
    brain_mask_img = nib.load(path_brain_mask)
    resampled_mask_img = resample_img(
        brain_mask_img,
        target_affine=affine_vol_fmri,
        target_shape=vol_fmri.shape[:-1],
        interpolation='nearest',
        force_resample=True
    )
    # Convert to bool
    resampled_mask = resampled_mask_img.get_fdata()
    resampled_mask = (resampled_mask != 0) # Convert to bool
    resampled_mask_img = nib.Nifti1Image(resampled_mask, 
                                        affine=resampled_mask_img.affine, 
                                        header=resampled_mask_img.header)

    # Save the resampled mask
    resampled_path = os.path.join(os.path.dirname(path_brain_mask), "resampled_brain_mask.nii.gz")
    resampled_mask_img.to_filename(resampled_path)

    # Normalize the time series of the volume data inside the mask
    vol_fmri_masked_ = vol_fmri[resampled_mask]
    vol_fmri_masked = np.zeros_like(vol_fmri)
    vol_fmri_masked[resampled_mask] = vol_fmri_masked_
    
    return vol_fmri_masked, resampled_mask, affine_vol_fmri


def fmri_vol2surf(vol_fmri_img, path_midthickness_l, path_midthickness_r):
    """
    An alternative to the Freesurfer project command.
    Projects fMRI volume data onto the cortical surface. 

    Args:
        vol_fmri_img (nib.Nifti1Image): The fMRI volume image to be projected onto the surface.
        path_midthickness_l (str): File path to the left hemisphere midthickness surface.
        path_midthickness_r (str): File path to the right hemisphere midthickness surface.

    Returns:
        tuple: A tuple containing:
            - surf_fmri_l (numpy.ndarray): The fMRI data projected onto the left hemisphere surface.
            - surf_fmri_r (numpy.ndarray): The fMRI data projected onto the right hemisphere surface.
    """
    surf_fmri_l = surface.vol_to_surf(vol_fmri_img,
                                      path_midthickness_l,
                                      radius=6)
    surf_fmri_r = surface.vol_to_surf(vol_fmri_img,
                                      path_midthickness_r,
                                      radius=6)
    
    if np.isnan(surf_fmri_l).any() or np.isnan(surf_fmri_r).any():
        print("NaN values in the surface data")
    
    # Normalized the time series of the surface data
    surf_fmri_l = (surf_fmri_l - np.mean(surf_fmri_l, axis=1, keepdims=True)) / np.std(surf_fmri_l, axis=1, keepdims=True)
    surf_fmri_r = (surf_fmri_r - np.mean(surf_fmri_r, axis=1, keepdims=True)) / np.std(surf_fmri_r, axis=1, keepdims=True)
    
    return surf_fmri_l, surf_fmri_r

def fmri_to_spatial_modes(vol_fmri, 
                          resampled_mask,
                          n_modes=380,
                          low_variance_threshold = 0.5):
    """
    Converts fMRI volume data to spatial modes using Singular Value Decomposition (SVD).

    Args:
        vol_fmri (numpy.ndarray float): 4D fMRI volume data.
        resampled_mask (numpy.ndarray bool): 3D resampled brain mask (bool).
        n_modes (int): Number of spatial modes to retain.
        low_variance_threshold (float): Threshold for removing voxels with low variance.

    Returns:
        numpy.ndarray: 2D array of spatial modes.
    """
    from scipy.linalg import svd
    mask_idx = np.where(resampled_mask)
    # Create the spatial modes
    fmri_masked = vol_fmri[mask_idx]
    # Remove voxels with low variance (thresholding by the variance of each voxel's time series)
    variance = np.var(fmri_masked, axis=1)
    fmri_masked = fmri_masked[variance > low_variance_threshold]
    
    fmri_m_normalized = (fmri_masked - np.mean(fmri_masked, axis=1, keepdims=True)) / np.std(fmri_masked, axis=1, keepdims=True)
    keep = ~np.isnan(fmri_m_normalized).any(axis=1) & ~np.isinf(fmri_m_normalized).any(axis=1)
    fmri_m_normalized = fmri_m_normalized[keep]
    # The principal components are the eigenvectors of S = X'*X./(n-1), but computed using SVD
    [U,sigma,V] = svd(fmri_m_normalized,full_matrices=False)
    # Project X onto the principal component axes
    # spatial_modes = U[:n_modes,:].T * sigma[:n_modes]
    
    return U[:n_modes,:]
    

def congrads_dim_reduction(vol_fmri, resampled_mask, low_variance_threshold=0.5):
    def pca(X):
        from scipy.linalg import svd

        # Center X by subtracting off column means
        X -= np.mean(X,0)

        # The principal components are the eigenvectors of S = X'*X./(n-1), but computed using SVD
        [U,sigma,V] = svd(X,full_matrices=False)

        # Project X onto the principal component axes
        Y = U*sigma

        # Convert the singular values to eigenvalues 
        sigma /= np.sqrt(X.shape[0]-1)
        evals = np.square(sigma)
        
        return V, Y, evals
    
    mask_idx = np.where(resampled_mask)
    # Create the spatial modes
    fmri_masked = vol_fmri[mask_idx]
    # Remove voxels with low variance (thresholding by the variance of each voxel's time series)
    variance = np.var(fmri_masked, axis=1)
    fmri_masked = fmri_masked[variance > low_variance_threshold]
    [evecs,Bhat,evals] = pca(fmri_masked)
    # PLEASE TELL ME THAT IT IS STUPID PLEASSEEEE
    
#%% Run the code
if __name__ == "__main__":
    # Paths
    SUBJECT = r"01"

    SUBJ_DIR = r"D:\DATA_min_preproc\dataset_study2\sub-" + SUBJECT
    path_func = SUBJ_DIR + r"\func\rwsraOB_TD_FBI_S" + SUBJECT + r"_007_Rest.nii"

    path_midthickness_r = SUBJ_DIR + r"\func\rh.midthickness.32k.surf.gii"
    path_midthickness_l = SUBJ_DIR + r"\func\lh.midthickness.32k.surf.gii"

    path_white_r = SUBJ_DIR + r"\func\rh.white.32k.surf.gii"
    path_white_l = SUBJ_DIR + r"\func\lh.white.32k.surf.gii"

    path_pial_r = SUBJ_DIR + r"\func\rh.pial.32k.surf.gii"
    path_pial_l = SUBJ_DIR + r"\func\lh.pial.32k.surf.gii"

    path_brain_mask = SUBJ_DIR + r"\sub" + SUBJECT + r"_freesurfer\mri\brainmask.mgz"

    path_midthickness_l_inflated = SUBJ_DIR + r"\func\lh.midthickness.inflated.32k.surf.gii"

    vol_fmri, resampled_mask, affine = load_volume_data(path_func, path_brain_mask)
    surf_fmri_l, surf_fmri_r = fmri_vol2surf(nib.load(path_func), path_midthickness_l, path_midthickness_r)
    
    modes = fmri_to_spatial_modes(vol_fmri, 
                          resampled_mask,
                          n_modes=380,
                          low_variance_threshold = 0.5)
# %%
